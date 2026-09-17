from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.documents import (
    DocumentSubmission,
    DocumentPermissionDeniedError,
    DocumentStatus,
    StoredDocument,
    StoredDocumentVersion,
    validate_document_availability,
)
from app.services.document_workflow import DocumentUploadService
from app.domain.users import SpaceRole


logger = logging.getLogger(__name__)


class DocumentNotFoundError(LookupError):
    pass


class DocumentRetryNotAllowedError(ValueError):
    pass


class DocumentManagementRepository(Protocol):
    async def has_space_access(self, *, space_id: UUID, user_id: UUID) -> bool: ...

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None: ...

    async def list_documents(self, space_id: UUID) -> list[StoredDocument]: ...

    async def search_documents(
        self, space_id: UUID, query: str, tag_id: UUID | None = None
    ) -> list[StoredDocument]: ...

    async def get_document(self, document_id: UUID) -> StoredDocument | None: ...

    async def retry_failed_document(
        self, document_id: UUID
    ) -> tuple[StoredDocument, StoredDocumentVersion] | None: ...

    async def mark_document_deleted(self, document_id: UUID) -> None: ...

    async def update_document_availability(
        self,
        document_id: UUID,
        *,
        is_enabled: bool | None,
        effective_at: datetime | None,
        expires_at: datetime | None,
    ) -> StoredDocument | None: ...

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

    async def list_documents(
        self, space_id: UUID, *, owner_user_id: UUID | None = None
    ) -> list[StoredDocument]:
        await self._require_owner_space(space_id, owner_user_id=owner_user_id)
        return await self._repository.list_documents(space_id)

    async def search_documents(
        self, space_id: UUID, *, query: str, tag_id: UUID | None = None, owner_user_id: UUID | None = None
    ) -> list[StoredDocument]:
        await self._require_owner_space(space_id, owner_user_id=owner_user_id)
        normalized = query.strip()
        if not normalized:
            return await self._repository.list_documents(space_id)
        return await self._repository.search_documents(space_id, normalized, tag_id)

    async def get_document(
        self, document_id: UUID, *, owner_user_id: UUID | None = None
    ) -> StoredDocument:
        document = await self._repository.get_document(document_id)
        if document is None or document.status == DocumentStatus.DELETED:
            raise DocumentNotFoundError("文档不存在。")
        await self._require_owner_space(document.space_id, owner_user_id=owner_user_id)
        return document

    async def retry(
        self, document_id: UUID, *, owner_user_id: UUID | None = None
    ) -> tuple[StoredDocument, StoredDocumentVersion]:
        document = await self._get_mutable_document(document_id, owner_user_id=owner_user_id)
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

    async def delete(self, document_id: UUID, *, owner_user_id: UUID | None = None) -> StoredDocument:
        document = await self._get_mutable_document(document_id, owner_user_id=owner_user_id)
        await self._repository.mark_document_deleted(document_id)
        await self._repository.commit()
        try:
            await self._dispatcher.enqueue_cleanup(document.storage_key)
        except Exception:
            # Retrieval is already disabled and the object can be cleaned up by
            # a later operational retry; never roll back the soft delete.
            logger.exception("document cleanup enqueue failed after soft delete")
        return document

    async def update_availability(
        self,
        document_id: UUID,
        *,
        is_enabled: bool | None,
        effective_at: datetime | None,
        expires_at: datetime | None,
        owner_user_id: UUID | None = None,
    ) -> StoredDocument:
        document = await self._get_mutable_document(document_id, owner_user_id=owner_user_id)
        validate_document_availability(
            effective_at=effective_at,
            expires_at=expires_at,
        )
        updated = await self._repository.update_document_availability(
            document.id,
            is_enabled=is_enabled,
            effective_at=effective_at,
            expires_at=expires_at,
        )
        if updated is None:
            raise DocumentNotFoundError("文档不存在。")
        await self._repository.commit()
        return updated

    async def _require_owner_space(self, space_id: UUID, *, owner_user_id: UUID | None) -> None:
        if owner_user_id is None:
            return
        role_reader = getattr(self._repository, "get_space_role", None)
        if role_reader is not None:
            role = await role_reader(space_id=space_id, user_id=owner_user_id)
            if role is None:
                raise DocumentNotFoundError("文档不存在。")
            if not self._role_at_least(role, SpaceRole.MEMBER):
                raise DocumentPermissionDeniedError("你没有访问此空间文档的权限。")
            return
        checker = getattr(self._repository, "has_space_access", None)
        if checker is None or not await checker(space_id=space_id, user_id=owner_user_id):
            raise DocumentNotFoundError("文档不存在。")

    async def _get_mutable_document(
        self, document_id: UUID, *, owner_user_id: UUID | None
    ) -> StoredDocument:
        document = await self.get_document(document_id, owner_user_id=owner_user_id)
        if owner_user_id is not None:
            role_reader = getattr(self._repository, "get_space_role", None)
            if role_reader is not None:
                role = await role_reader(space_id=document.space_id, user_id=owner_user_id)
                if role is None:
                    raise DocumentNotFoundError("文档不存在。")
                if not self._role_at_least(role, SpaceRole.EDITOR):
                    raise DocumentPermissionDeniedError("你没有修改此空间文档的权限。")
        return document

    @staticmethod
    def _role_at_least(actual: SpaceRole, minimum: SpaceRole) -> bool:
        order = {SpaceRole.MEMBER: 0, SpaceRole.EDITOR: 1, SpaceRole.OWNER: 2}
        return order[actual] >= order[minimum]


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

    async def list_documents(self, space_id: UUID, **kwargs: object) -> list[StoredDocument]:
        return await self._management_service.list_documents(space_id, **kwargs)  # type: ignore[arg-type]

    async def search_documents(self, space_id: UUID, **kwargs: object) -> list[StoredDocument]:
        return await self._management_service.search_documents(space_id, **kwargs)  # type: ignore[arg-type]

    async def get_document(self, document_id: UUID, **kwargs: object) -> StoredDocument:
        return await self._management_service.get_document(document_id, **kwargs)  # type: ignore[arg-type]

    async def retry(
        self, document_id: UUID, **kwargs: object
    ) -> tuple[StoredDocument, StoredDocumentVersion]:
        return await self._management_service.retry(document_id, **kwargs)  # type: ignore[arg-type]

    async def delete(self, document_id: UUID, **kwargs: object) -> StoredDocument:
        return await self._management_service.delete(document_id, **kwargs)  # type: ignore[arg-type]

    async def update_availability(self, document_id: UUID, **kwargs: object) -> StoredDocument:
        return await self._management_service.update_availability(document_id, **kwargs)  # type: ignore[arg-type]
