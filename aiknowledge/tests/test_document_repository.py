from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.documents import (
    DocumentStatus,
    DocumentVersionStatus,
    StoredDocument,
    StoredDocumentVersion,
)
from app.domain.spaces import SpaceVisibility
from app.infrastructure.database.document_repository import SqlAlchemyDocumentRepository
from app.infrastructure.database.models import (
    CategoryRecord,
    DocumentRecord,
    DocumentVersionRecord,
    KnowledgeSpaceRecord,
)


class FakeSession:
    def __init__(self) -> None:
        self.records: dict[type, dict[object, object]] = {}
        self.added: list[object] = []
        self.flushes = 0
        self.commits = 0

    def add(self, record: object) -> None:
        self.added.append(record)
        self.records.setdefault(type(record), {})[record.id] = record  # type: ignore[attr-defined]

    async def get(self, model: type, record_id: object, **_: object) -> object | None:
        return self.records.get(model, {}).get(record_id)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_document_repository_maps_processing_document_and_version_records() -> None:
    session = FakeSession()
    repository = SqlAlchemyDocumentRepository(session)  # type: ignore[arg-type]
    now = datetime(2026, 9, 11, tzinfo=UTC)
    document = StoredDocument(
        id=uuid4(),
        space_id=uuid4(),
        category_id=None,
        original_filename="资料.txt",
        storage_key="documents/id/source.txt",
        mime_type="text/plain",
        size_bytes=3,
        sha256="a" * 64,
        status=DocumentStatus.PROCESSING,
        active_version_id=None,
        created_at=now,
        updated_at=now,
    )
    version = StoredDocumentVersion(
        id=uuid4(),
        document_id=document.id,
        version_number=1,
        parser_version="mvp-parser-v1",
        embedding_provider="local",
        embedding_model="BAAI/bge-large-zh-v1.5",
        embedding_dimension=1024,
        chunk_config={"max_characters": 1800},
        status=DocumentVersionStatus.PROCESSING,
        created_at=now,
    )

    await repository.create_processing_document(document, version)
    context = await repository.get_processing_context(version.id)

    assert isinstance(session.added[0], DocumentRecord)
    assert isinstance(session.added[1], DocumentVersionRecord)
    assert context == (document, version)
    assert session.flushes == 1


@pytest.mark.asyncio
async def test_document_repository_validates_public_category_scope_before_persisting() -> None:
    session = FakeSession()
    repository = SqlAlchemyDocumentRepository(session)  # type: ignore[arg-type]
    now = datetime(2026, 9, 11, tzinfo=UTC)
    space = KnowledgeSpaceRecord(
        id=uuid4(),
        name="公开空间",
        description=None,
        visibility=SpaceVisibility.PUBLIC,
        guest_feedback_enabled=False,
        created_at=now,
        updated_at=now,
    )
    category = CategoryRecord(
        id=uuid4(),
        space_id=space.id,
        name="分类",
        description=None,
        is_open=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )
    session.add(space)
    session.add(category)

    assert not await repository.is_valid_document_scope(
        space_id=space.id, category_id=None
    )
    assert await repository.is_valid_document_scope(
        space_id=space.id, category_id=category.id
    )
