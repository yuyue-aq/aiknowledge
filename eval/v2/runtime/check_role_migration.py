"""Read legacy upgrade invariants and transactionally test unique ownership."""
import asyncio,json
from pathlib import Path
from uuid import UUID
import asyncpg
from app.core.config import get_settings

async def main():
    settings=get_settings();dsn=str(settings.database_url).replace("postgresql+asyncpg://","postgresql://")
    assert dsn.endswith("/v2_acceptance")
    checks=[]
    legacy=await asyncpg.connect(dsn.rsplit("/",1)[0]+"/v2_upgrade_test")
    assert await legacy.fetchval("SELECT version_num FROM alembic_version")=="20261002_0022"
    assert await legacy.fetchval("SELECT count(*) FROM document_versions")==2
    assert await legacy.fetchval("SELECT count(*) FROM chunks")==1
    assert await legacy.fetchval("SELECT char_start FROM chunks") is None
    checks.append("populated_0016_to_0022_preserves_versions_chunks_unknown_coordinates")
    await legacy.close()
    db=await asyncpg.connect(dsn)
    sid=UUID(json.loads(Path("/runtime/space-roles-report.json").read_text())["space_id"])
    admin=await db.fetchval("SELECT user_id FROM space_memberships WHERE space_id=$1 AND role='ADMIN'",sid)
    assert admin
    try:
        async with db.transaction():
            await db.execute("UPDATE space_memberships SET role='OWNER' WHERE space_id=$1 AND user_id=$2",sid,admin)
    except asyncpg.UniqueViolationError:
        checks.append("database_rejects_second_owner_without_demotion_or_data_loss")
    else:raise AssertionError("Unique owner constraint missing")
    assert await db.fetchval("SELECT count(*) FROM space_memberships WHERE space_id=$1 AND role='OWNER'",sid)==1
    await db.close()
    Path("/tmp/role-migration-report.json").write_text(json.dumps({"status":"PASSED","checks":checks},indent=2))
    print("PASS populated upgrade and unique owner database constraint")

asyncio.run(main())
