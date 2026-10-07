from hashlib import sha256
import json


def knowledge_manifest(chunks: list[dict], *, access_revision: int, knowledge_revision: int) -> dict:
    stable = {'access_revision': access_revision, 'knowledge_revision': knowledge_revision,
        'document_versions': sorted({chunk['document_version_id'] for chunk in chunks}),
        'chunks': sorted(chunks, key=lambda chunk: (chunk['document_id'], chunk['document_version_id'], chunk['chunk_id']))}
    digest = sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return {**stable, 'manifest_digest': digest, 'schema_version': 2}
