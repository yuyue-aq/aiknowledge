"""Validate a populated synthetic 0016 database after upgrade to 0021."""
import asyncio
import json
import asyncpg

DSN = 'postgresql://v2test:v2-isolated-local-only@postgres:5432/v2_upgrade_test'
SPACE = '10000000-0000-0000-0000-000000000001'


async def main():
    checks = []
    connection = await asyncpg.connect(DSN)
    assert await connection.fetchval('SELECT version_num FROM alembic_version') == '20261001_0021'
    checks.append('populated_0016_upgraded_to_0021')
    assert await connection.fetchval('SELECT count(*) FROM document_versions') == 2
    assert await connection.fetchval('SELECT count(*) FROM chunks') == 1
    checks.append('legacy_versions_chunks_preserved')
    active = await connection.fetchval('SELECT source_snapshot FROM document_versions WHERE version_number=2')
    assert json.loads(active)['storage_key'] == 'synthetic/legacy.txt'
    assert await connection.fetchval('SELECT source_snapshot FROM document_versions WHERE version_number=1') is None
    checks.append('only_active_legacy_source_backfilled')
    assert await connection.fetchval('SELECT source_block_id FROM chunks') is None
    assert await connection.fetchval('SELECT char_start FROM chunks') is None
    checks.append('legacy_unknown_coordinates_remain_unknown')
    row = await connection.fetchrow('SELECT access_revision,knowledge_revision FROM knowledge_spaces')

    async def change_category(category_id):
        other = await asyncpg.connect(DSN)
        try:
            async with other.transaction():
                await other.execute('UPDATE categories SET is_open=false WHERE id=$1::uuid', category_id)
                await asyncio.sleep(.1)
        finally:
            await other.close()

    await asyncio.gather(change_category('10000000-0000-0000-0000-000000000002'),
                         change_category('10000000-0000-0000-0000-000000000007'))
    after = await connection.fetchrow('SELECT access_revision,knowledge_revision FROM knowledge_spaces')
    assert after['access_revision'] == row['access_revision'] + 2
    assert after['knowledge_revision'] == row['knowledge_revision'] + 2
    checks.append('concurrent_revision_increments_not_lost')
    # Validate pgvector cosine similarity against known basis vectors.
    score = await connection.fetchval("SELECT 1-(embedding <=> ((ARRAY[1.0] || array_fill(0.0,ARRAY[1023]))::vector)) FROM chunks")
    assert abs(score - 1) < 1e-9
    checks.append('pgvector_cosine_known_basis')
    await connection.close()
    print(json.dumps({'mode': 'real_postgresql_populated_legacy_upgrade', 'status': 'PASSED', 'checks': checks}, indent=2))


asyncio.run(main())
