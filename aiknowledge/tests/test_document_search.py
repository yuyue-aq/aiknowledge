from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.documents import DocumentStatus, StoredDocument
from app.services.document_management import DocumentManagementService


def build_document(name: str) -> StoredDocument:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    return StoredDocument(
        id=uuid4(),
        space_id=uuid4(),
        category_id=None,
        original_filename=name,
        storage_key=f"documents/{name}",
        mime_type="text/plain",
        size_bytes=4,
        sha256="a" * 64,
        status=DocumentStatus.READY,
        active_version_id=uuid4(),
        created_at=now,
        updated_at=now,
    )


class FakeRepository:
    def __init__(self, document: StoredDocument) -> None:
        self.document = document

    async def search_documents(self, space_id: UUID, query: str, tag_id: UUID | None = None) -> list[StoredDocument]:
        if space_id != self.document.space_id:
            return []
        return [self.document] if query.lower() in self.document.original_filename.lower() else []

    async def get_document(self, document_id: UUID) -> StoredDocument | None:
        return self.document if document_id == self.document.id else None


class FakeDispatcher:
    async def enqueue_processing(self, version_id: UUID) -> None: pass
    async def enqueue_cleanup(self, object_key: str) -> None: pass


@pytest.mark.asyncio
async def test_document_search_delegates_query_and_tag_filter() -> None:
    document = build_document("产品手册.md")
    repository = FakeRepository(document)
    service = DocumentManagementService(repository=repository, dispatcher=FakeDispatcher())

    result = await service.search_documents(document.space_id, query="产品", tag_id=uuid4())

    assert result == [document]


@pytest.mark.asyncio
async def test_tag_only_search_keeps_the_tag_filter() -> None:
    document = build_document("产品手册.md")
    tag_id = uuid4()

    class TaggedRepository(FakeRepository):
        async def list_documents(self, space_id):
            raise AssertionError("tag filter must not be discarded")

        async def search_documents(self, space_id, query, tag_id=None):
            assert query == ""
            assert tag_id == expected_tag
            return [self.document]

    expected_tag = tag_id
    service = DocumentManagementService(repository=TaggedRepository(document), dispatcher=FakeDispatcher())
    assert await service.search_documents(document.space_id, query="  ", tag_id=tag_id) == [document]
