from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.domain.retrieval import RetrievalMetadataFilter


def test_metadata_filter_normalizes_order_and_has_stable_snapshot():
    category_a, category_b = uuid4(), uuid4()
    value = RetrievalMetadataFilter(
        category_ids=(category_b, category_a, category_a),
        tag_ids=(category_a,),
        formats=("TABLE", "markdown", "table"),
        version_min=2,
        version_max=5,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert value.category_ids == tuple(sorted((category_a, category_b), key=str))
    assert value.formats == ("markdown", "table")
    assert value.snapshot() == {
        "category_ids": [str(item) for item in value.category_ids],
        "tag_ids": [str(category_a)],
        "formats": ["markdown", "table"],
        "version_min": 2,
        "version_max": 5,
        "valid_from": "2026-01-01T00:00:00+00:00",
        "valid_to": None,
    }
    assert RetrievalMetadataFilter.from_snapshot(value.snapshot()) == value


@pytest.mark.parametrize(
    "kwargs",
    [
        {"formats": ("exe",)},
        {"version_min": 0},
        {"version_min": 4, "version_max": 2},
        {"valid_from": datetime(2026, 1, 2, tzinfo=timezone.utc), "valid_to": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        {"valid_from": datetime(2026, 1, 1)},
    ],
)
def test_metadata_filter_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        RetrievalMetadataFilter(**kwargs)


def test_metadata_filter_compiles_into_one_sql_scope_for_all_dimensions():
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from app.infrastructure.database.conversation_repository import SqlAlchemyConversationRepository
    from app.infrastructure.database.models import ChunkRecord

    metadata_filter = RetrievalMetadataFilter(
        category_ids=(uuid4(),),
        tag_ids=(uuid4(),),
        formats=("pdf", "markdown"),
        version_min=2,
        version_max=4,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    statement = SqlAlchemyConversationRepository._apply_metadata_filter(
        select(ChunkRecord.id), metadata_filter
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "categories" in sql
    assert "document_tags" in sql and "knowledge_tags" in sql
    assert "document_versions" in sql and "documents.active_version_id" in sql
    assert "documents.original_filename" in sql
    assert "documents.effective_at" in sql and "documents.expires_at" in sql


@pytest.mark.asyncio
async def test_owner_search_freezes_metadata_filter_into_scope_and_run():
    from app.domain.retrieval import RetrievalResult
    from app.services.owner_retrieval import OwnerRetrievalService

    class Repository:
        def __init__(self):
            self.filters = []
            self.run = None

        async def resolve_owner_scope(self, *, space_id, user_id, metadata_filter=None):
            from app.domain.retrieval import RetrievalScope
            from datetime import datetime, timezone

            self.filters.append(metadata_filter)
            return RetrievalScope(space_id, user_id, 1, 2, datetime.now(timezone.utc), metadata_filter)

        async def retrieve(self, *, scope, embedding, limit):
            self.filters.append(scope.metadata_filter)
            return []

        async def get_current_chunks(self, *, scope, chunk_ids):
            self.filters.append(scope.metadata_filter)
            return []

        async def add_run(self, run):
            self.run = run

        async def keyword_corpus(self, *, scope, limit):
            self.filters.append(scope.metadata_filter)
            return []

    class Retrieval:
        async def search(self, *, question, fetch, top_k):
            from app.domain.retrieval import RetrievalResult

            return RetrievalResult(question, top_k, (), {"embedding": 0, "search": 0, "total": 0})

    repository = Repository()
    metadata_filter = RetrievalMetadataFilter(formats=("pdf",), version_min=2)
    service = OwnerRetrievalService(repository=repository, retrieval=Retrieval(), model_name="test")

    run, _ = await service.search(
        space_id=uuid4(), user_id=uuid4(), question="question", metadata_filter=metadata_filter
    )

    assert repository.filters and all(value == metadata_filter for value in repository.filters)
    assert run.scope.metadata_filter == metadata_filter
    assert run.config_snapshot["metadata_filter"] == metadata_filter.snapshot()
