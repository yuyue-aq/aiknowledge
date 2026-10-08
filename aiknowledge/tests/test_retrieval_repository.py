from datetime import UTC, datetime
from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.infrastructure.database.models import ChunkRecord, KnowledgeSpaceRecord, RetrievalRunRecord
from app.infrastructure.database.retrieval_repository import SqlAlchemyRetrievalRepository


class Session:
    def __init__(self):
        self.statement = None
        self.rows = []
        self.added = []

    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(first=lambda: None, all=lambda: self.rows)

    def add(self, record):
        self.added.append(record)

    async def flush(self):
        pass


@pytest.mark.asyncio
async def test_document_detail_lookup_filters_document_space_and_deleted_before_reading_chunks():
    from app.domain.retrieval import RetrievalScope
    session = Session()
    async def scalar(statement):
        session.statement = statement
        return None
    session.scalar = scalar
    scope = RetrievalScope(uuid4(), uuid4(), 0, 0, datetime.now(UTC))
    assert await SqlAlchemyRetrievalRepository(session).get_document_detail(scope=scope, document_id=uuid4()) is None
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    for required in ('documents.id =', 'documents.space_id =', 'documents.deleted_at IS NULL'):
        assert required in sql


@pytest.mark.asyncio
async def test_diagnostic_scope_sql_requires_owner_and_active_space():
    session = Session()
    repo = SqlAlchemyRetrievalRepository(session)
    assert await repo.resolve_owner_scope(space_id=uuid4(), user_id=uuid4()) is None
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert 'space_memberships.role' in sql
    assert 'knowledge_spaces.owner_user_id' in sql
    assert 'knowledge_spaces.deleted_at IS NULL' in sql
    assert 'knowledge_spaces.access_revision' in sql
    assert 'knowledge_spaces.knowledge_revision' in sql
    assert 'OWNER' in session.statement.compile().params.values()
    assert 'ADMIN' in session.statement.compile().params.values()
    assert 'TEAM' in session.statement.compile().params.values()
    assert 'knowledge_spaces.kind' in sql


def test_v2_schema_preserves_unknown_legacy_source_offsets_and_durable_run_ids():
    for field in ('source_block_id', 'char_start', 'char_end'):
        assert ChunkRecord.__table__.c[field].nullable
    assert not KnowledgeSpaceRecord.__table__.c.access_revision.nullable
    assert not KnowledgeSpaceRecord.__table__.c.knowledge_revision.nullable
    assert RetrievalRunRecord.__table__.c.chunk_ids.type.__class__.__name__ == 'JSONB'
    assert 'content' not in RetrievalRunRecord.__table__.c


@pytest.mark.asyncio
async def test_current_evidence_query_filters_id_scope_versions_and_time():
    from app.domain.retrieval import RetrievalScope
    session = Session()
    scope = RetrievalScope(uuid4(), uuid4(), 0, 0, datetime.now(UTC))
    await SqlAlchemyRetrievalRepository(session).get_current_chunks(scope=scope, chunk_ids=(uuid4(),))
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    for required in ('chunks.space_id =', 'chunks.id IN', 'documents.active_version_id = chunks.document_version_id',
                     'documents.is_enabled IS true', 'documents.expires_at > clock_timestamp()', 'documents.deleted_at IS NULL'):
        assert required in sql


@pytest.mark.asyncio
async def test_keyword_corpus_uses_live_authorization_predicate_without_vector_distance():
    from app.domain.retrieval import RetrievalScope
    session=Session();scope=RetrievalScope(uuid4(),uuid4(),0,0,datetime.now(UTC))
    await SqlAlchemyRetrievalRepository(session).keyword_corpus(scope=scope,limit=101)
    sql=str(session.statement.compile(dialect=postgresql.dialect()))
    for required in ('chunks.space_id =','documents.active_version_id = chunks.document_version_id',
                     'documents.is_enabled IS true','documents.expires_at > clock_timestamp()',
                     'documents.effective_at <= clock_timestamp()','documents.deleted_at IS NULL','chunks.is_active IS true'):
        assert required in sql
    assert '<=>' not in sql
    assert 101 in session.statement.compile().params.values()
