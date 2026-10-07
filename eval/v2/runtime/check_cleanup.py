"""Read-only proof that the API/beat removed this synthetic document's objects."""
import asyncio
import json
from pathlib import Path
import time

import asyncpg
from minio import Minio
from minio.error import S3Error


async def main():
    report = json.loads(Path('/runtime/lifecycle_report.json').read_text())
    assert report['status'] == 'PASSED', 'Run lifecycle acceptance first'
    did = report['document_id']
    connection = await asyncpg.connect('postgresql://v2test:v2-isolated-local-only@postgres:5432/v2_acceptance')
    storage = Minio('minio:9000', access_key='v2test', secret_key='v2-isolated-local-only', secure=False)
    rows = await connection.fetch('SELECT source_snapshot FROM document_versions WHERE document_id=$1::uuid', did)
    keys = {json.loads(row['source_snapshot'])['storage_key'] for row in rows if row['source_snapshot']}
    assert len(keys) == 3, 'Expected sources for original, failed and updated versions'
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        done = await connection.fetchval('SELECT cleanup_completed_at IS NOT NULL FROM documents WHERE id=$1::uuid AND deleted_at IS NOT NULL', did)
        missing = 0
        for key in keys:
            try:
                await asyncio.to_thread(storage.stat_object, 'v2-acceptance', key)
            except S3Error as error:
                if error.code not in ('NoSuchKey', 'NoSuchObject', 'NoSuchVersion'):
                    raise
                missing += 1
        if done and missing == len(keys):
            print(json.dumps({'mode': 'real_api_beat_minio_cleanup', 'status': 'PASSED',
                              'document_id': did, 'version_source_count': len(keys), 'missing_objects': missing,
                              'completion_marker': True}, indent=2))
            await connection.close()
            return
        await asyncio.sleep(2)
    raise TimeoutError('All synthetic version sources must be removed before cleanup completes')


asyncio.run(main())
