from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.conversations import EvalResult
from app.domain.rag import AnswerStatus
from app.infrastructure.database.evaluation_repository import SqlAlchemyEvaluationRepository
from app.services.evaluation_snapshot import knowledge_manifest


class Session:
    def __init__(self):
        self.statement = None
        self.added = []
    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(scalar_one_or_none=lambda: None)
    def add(self, value):
        self.added.append(value)


@pytest.mark.asyncio
async def test_recovery_scan_is_bounded_and_selects_only_stale_pending_or_expired_workers():
    session = Session()
    async def scalars(statement):
        session.statement = statement
        return SimpleNamespace(all=lambda: [])
    session.scalars = scalars
    assert await SqlAlchemyEvaluationRepository(session).list_recoverable_runs(limit=20) == []
    compiled = session.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert 'LIMIT' in sql
    assert 'eval_runs.lease_expires_at < clock_timestamp()' in sql
    assert 'PENDING' in compiled.params.values()
    assert 'RUNNING' in compiled.params.values()
    assert 'FAILED' not in compiled.params.values()


@pytest.mark.asyncio
async def test_run_status_read_refreshes_identity_cache_after_ambiguous_delivery():
    session = Session()
    async def get(model, run_id, **options):
        assert options.get('populate_existing') is True, 'a stale cached PENDING run must not replace a claimed RUNNING run'
        return None
    session.get = get
    assert await SqlAlchemyEvaluationRepository(session).get_run(uuid4()) is None


@pytest.mark.asyncio
async def test_atomic_claim_only_takes_pending_or_failed_or_expired_leases():
    session = Session()
    result = await SqlAlchemyEvaluationRepository(session).claim_run(uuid4(), lease_token='worker-1', lease_seconds=1200)
    assert result is None
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert 'UPDATE eval_runs' in sql
    assert 'eval_runs.lease_expires_at < clock_timestamp()' in sql
    assert 'RETURNING' in sql
    assert 'lease_owner' in sql
    assert 'PENDING' in session.statement.compile().params.values()
    assert 'FAILED' in session.statement.compile().params.values()


@pytest.mark.asyncio
async def test_expired_or_replaced_worker_cannot_write_a_result():
    session = Session()
    result = EvalResult(uuid4(), uuid4(), uuid4(), AnswerStatus.ANSWERED, '答案', 1)
    saved = await SqlAlchemyEvaluationRepository(session).checkpoint_result(result, lease_token='old-worker', lease_seconds=1200)
    assert saved is False
    assert session.added == []
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert 'eval_runs.lease_owner =' in sql
    assert 'eval_runs.lease_expires_at > clock_timestamp()' in sql


def test_manifest_digest_is_stable_sorted_and_changes_with_source_version_or_scope():
    first = {'chunk_id': 'b', 'document_id': 'd', 'document_version_id': 'v', 'content_hash': '2'}
    second = {'chunk_id': 'a', 'document_id': 'd', 'document_version_id': 'v', 'content_hash': '1'}
    left = knowledge_manifest([first, second], access_revision=1, knowledge_revision=2)
    right = knowledge_manifest([second, first], access_revision=1, knowledge_revision=2)
    assert left['manifest_digest'] == right['manifest_digest']
    assert left['document_versions'] == ['v']
    assert knowledge_manifest([first], access_revision=1, knowledge_revision=2)['manifest_digest'] != left['manifest_digest']
    assert knowledge_manifest([first, second], access_revision=2, knowledge_revision=2)['manifest_digest'] != left['manifest_digest']
