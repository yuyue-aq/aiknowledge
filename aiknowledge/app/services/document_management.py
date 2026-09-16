from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from app.domain.documents import (
    DocumentSubmission,
    DocumentStatus,
    StoredDocument,
    StoredDocumentVersion,
)
from app.services.document_workflow import DocumentUploadService


logger = logging.getLogger(__name__)


class DocumentNotFoundError(LookupError):
    pass


class DocumentRetryNotAllowedError(ValueError):
    pass


class DocumentManagementRepository(Protocol):
    async def list_documents(self, space_id: UUID) -> list[StoredDocument]: ...

    async def get_document(self, document_id: UUID) -> StoredDocument | None: ...

    async def retry_failed_document(
        self, document_id: UUID
    ) -> tuple[StoredDocument, StoredDocumentVersion] | None: ...

    async def mark_document_deleted(self, document_id: UUID) -> None: ...

    async def commit(self) -> None: ...


class DocumentDispatcher(Protocol):
    async def enqueue_processing(self, version_id: UUID) -> None: ...

    async def enqueue_cleanup(self, object_key: str) -> None: ...


class DocumentManagementService:
    def __init__(
        self, *, repository: DocumentManagementRepository, dispatcher: DocumentDispatcher
    ) -> None:
        self._repository = repository
        self._dispatcher = dispatcher

    async def list_documents(self, space_id: UUID) -> list[StoredDocument]:
        return await self._repository.list_documents(space_id)

    async def get_document(self, document_id: UUID) -> StoredDocument:
        document = await self._repository.get_document(document_id)
        if document is None or document.status == DocumentStatus.DELETED:
            raise DocumentNotFoundError("文档不存在。")
        return document

    async def retry(
        self, document_id: UUID
    ) -> tuple[StoredDocument, StoredDocumentVersion]:
        document = await self.get_document(document_id)
        if document.status != DocumentStatus.FAILED:
            raise DocumentRetryNotAllowedError("只有处理失败的文档可以重试。")
        retried = await self._repository.retry_failed_document(document_id)
        if retried is None:
            raise DocumentRetryNotAllowedError("当前文档无法重试。")
        await self._repository.commit()
        try:
            await self._dispatcher.enqueue_processing(retried[1].id)
        except Exception:
            # The durable PROCESSING state can be retried by the same endpoint;
            # never roll it back after a successful commit.
            pass
        return retried

    async def delete(self, document_id: UUID) -> StoredDocument:
        document = await self.get_document(document_id)
        await self._repository.mark_document_deleted(document_id)
        await self._repository.commit()
        try:
            await self._dispatcher.enqueue_cleanup(document.storage_key)
        except Exception:
            # Retrieval is already disabled and the object can be cleaned up by
            # a later operational retry; never roll back the soft delete.
            logger.exception("document cleanup enqueue failed after soft delete")
        return document


class DocumentApplicationService:
    """Compose upload and management use cases over one request transaction."""

    def __init__(
        self,
        *,
        upload_service: DocumentUploadService,
        management_service: DocumentManagementService,
    ) -> None:
        self._upload_service = upload_service
        self._management_service = management_service

    async def upload(self, **kwargs: object) -> DocumentSubmission:
        return await self._upload_service.upload(**kwargs)

    async def list_documents(self, space_id: UUID) -> list[StoredDocument]:
        return await self._management_service.list_documents(space_id)

    async def get_document(self, document_id: UUID) -> StoredDocument:
        return await self._management_service.get_document(document_id)

    async def retry(
        self, document_id: UUID
    ) -> tuple[StoredDocument, StoredDocumentVersion]:
        return await self._management_service.retry(document_id)

    async def delete(self, document_id: UUID) -> StoredDocument:
        return await self._management_service.delete(document_id)
