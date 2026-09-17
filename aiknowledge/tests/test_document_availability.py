from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.domain.documents import (
    DocumentStatus,
    DocumentAvailabilityError,
    StoredDocument,
    is_document_available,
)
from app.services.document_management import DocumentManagementService


def build_document() -> StoredDocument:
    now = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)
    return StoredDocument(
        id=uuid4(),
        space_id=uuid4(),
        category_id=None,
        original_filename="资料.txt",
        storage_key="documents/source.txt",
        mime_type="text/plain",
        size_bytes=4,
        sha256="a" * 64,
        status=DocumentStatus.READY,
        active_version_id=uuid4(),
        created_at=now,
        updated_at=now,
        is_enabled=True,
        effective_at=None,
        expires_at=None,
    )


@pytest.mark.parametrize(
    ("enabled", "effective_at", "expires_at", "expected"),
    [
        (True, None, None, True),
        (False, None, None, False),
        (True, datetime(2026, 9, 17, 9, tzinfo=UTC), None, False),
        (True, datetime(2026, 9, 17, 7, tzinfo=UTC), datetime(2026, 9, 17, 9, tzinfo=UTC), True),
        (True, None, datetime(2026, 9, 17, 7, tzinfo=UTC), False),
    ],
)
def test_document_availability_is_time_and_status_aware(
    enabled: bool,
    effective_at: datetime | None,
    expires_at: datetime | None,
    expected: bool,
) -> None:
    document = replace(
        build_document(),
        is_enabled=enabled,
        effective_at=effective_at,
        expires_at=expires_at,
    )

    assert is_document_available(
        document,
        now=datetime(2026, 9, 17, 8, tzinfo=UTC),
    ) is expected


class FakeRepository:
    def __init__(self, document: StoredDocument) -> None:
        self.document = document
        self.commits = 0

    async def get_document(self, document_id: UUID) -> StoredDocument | None:
        return self.document if document_id == self.document.id else None

    async def update_document_availability(
        self,
        document_id: UUID,
        *,
        is_enabled: bool | None,
        effective_at: datetime | None,
        expires_at: datetime | None,
    ) -> StoredDocument | None:
        if document_id != self.document.id:
            return None
        self.document = replace(
            self.document,
            is_enabled=self.document.is_enabled if is_enabled is None else is_enabled,
            effective_at=effective_at,
            expires_at=expires_at,
        )
        return self.document

    async def commit(self) -> None:
        self.commits += 1


class FakeDispatcher:
    async def enqueue_processing(self, version_id: UUID) -> None:
        pass

    async def enqueue_cleanup(self, object_key: str) -> None:
        pass


@pytest.mark.asyncio
async def test_update_availability_commits_and_returns_document() -> None:
    document = build_document()
    repository = FakeRepository(document)
    service = DocumentManagementService(
        repository=repository,
        dispatcher=FakeDispatcher(),
    )

    updated = await service.update_availability(
        document.id,
        is_enabled=False,
        effective_at=None,
        expires_at=datetime(2026, 9, 18, tzinfo=UTC),
    )

    assert updated.is_enabled is False
    assert updated.expires_at == datetime(2026, 9, 18, tzinfo=UTC)
    assert repository.commits == 1


@pytest.mark.asyncio
async def test_update_availability_rejects_expiration_before_effective_time() -> None:
    document = build_document()
    repository = FakeRepository(document)
    service = DocumentManagementService(
        repository=repository,
        dispatcher=FakeDispatcher(),
    )

    with pytest.raises(DocumentAvailabilityError):
        await service.update_availability(
            document.id,
            is_enabled=True,
            effective_at=datetime(2026, 9, 19, tzinfo=UTC),
            expires_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
