from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.documents import (
    DocumentStatus,
    DocumentVersionStatus,
    StoredDocument,
    StoredDocumentVersion,
)
from app.services.document_management import DocumentManagementService
from app.domain.users import SpaceRole
from app.services.document_management import DocumentPermissionDeniedError


class FakeRepository:
    def __init__(self, document: StoredDocument, version: StoredDocumentVersion) -> None:
        self.document = document
        self.version = version
        self.deleted: UUID | None = None
        self.commits = 0

    async def list_documents(self, space_id: UUID) -> list[StoredDocument]:
        return [self.document] if self.document.space_id == space_id else []

    async def get_document(self, document_id: UUID) -> StoredDocument | None:
        return self.document if self.document.id == document_id else None

    async def retry_failed_document(self, document_id: UUID):  # type: ignore[no-untyped-def]
        if document_id != self.document.id:
            return None
        return self.document, self.version

    async def mark_document_deleted(self, document_id: UUID) -> None:
        self.deleted = document_id

    async def commit(self) -> None:
        self.commits += 1


class RoleAwareRepository(FakeRepository):
    def __init__(self, document: StoredDocument, version: StoredDocumentVersion, role: SpaceRole) -> None:
        super().__init__(document, version)
        self.role = role

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        return self.role if space_id == self.document.space_id else None


class FakeDispatcher:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.ids: list[UUID] = []
        self.cleanup_keys: list[str] = []
        self.commits_at_dispatch: int | None = None
        self.commits_at_cleanup: int | None = None

    async def enqueue_processing(self, version_id: UUID) -> None:
        self.commits_at_dispatch = self.repository.commits
        self.ids.append(version_id)

    async def enqueue_cleanup(self, object_key: str) -> None:
        self.commits_at_cleanup = self.repository.commits
        self.cleanup_keys.append(object_key)


def build_records() -> tuple[StoredDocument, StoredDocumentVersion]:
    now = datetime(2026, 9, 11, tzinfo=UTC)
    document = StoredDocument(
        id=uuid4(),
        space_id=uuid4(),
        category_id=None,
        original_filename="失败资料.txt",
        storage_key="documents/id/source.txt",
        mime_type="text/plain",
        size_bytes=5,
        sha256="a" * 64,
        status=DocumentStatus.FAILED,
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
        chunk_config={},
        status=DocumentVersionStatus.FAILED,
        created_at=now,
    )
    return document, version


@pytest.mark.asyncio
async def test_retry_commits_processing_state_before_dispatching_the_same_version_id() -> None:
    document, version = build_records()
    repository = FakeRepository(document, version)
    dispatcher = FakeDispatcher(repository)
    service = DocumentManagementService(repository=repository, dispatcher=dispatcher)

    retried = await service.retry(document.id)

    assert retried == (document, version)
    assert dispatcher.ids == [version.id]
    assert dispatcher.commits_at_dispatch == 1


@pytest.mark.asyncio
async def test_delete_marks_document_unavailable_before_returning() -> None:
    document, version = build_records()
    repository = FakeRepository(document, version)
    dispatcher = FakeDispatcher(repository)
    service = DocumentManagementService(repository=repository, dispatcher=dispatcher)

    deleted = await service.delete(document.id)

    assert deleted == document
    assert repository.deleted == document.id
    assert repository.commits == 1
    assert dispatcher.cleanup_keys == [document.storage_key]
    assert dispatcher.commits_at_cleanup == 1


@pytest.mark.asyncio
async def test_read_only_member_can_list_but_cannot_retry_or_delete_documents() -> None:
    document, version = build_records()
    repository = RoleAwareRepository(document, version, SpaceRole.MEMBER)
    service = DocumentManagementService(repository=repository, dispatcher=FakeDispatcher(repository))
    member_id = uuid4()

    assert await service.list_documents(document.space_id, owner_user_id=member_id) == [document]
    with pytest.raises(DocumentPermissionDeniedError):
        await service.retry(document.id, owner_user_id=member_id)
    with pytest.raises(DocumentPermissionDeniedError):
        await service.delete(document.id, owner_user_id=member_id)
