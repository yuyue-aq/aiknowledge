from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session, get_optional_current_user, get_current_user
from app.core.errors import AppError
from app.domain.documents import (
    DocumentPermissionDeniedError,
    DocumentSubmission,
    DocumentStatus,
    DocumentVersionConflictError,
    StoredDocument,
)
from app.services.document_workflow import (
    DocumentAlreadyExistsError,
    DocumentScopeError,
    DocumentUploadError,
)
from app.services.document_management import (
    DocumentNotFoundError,
    DocumentRetryNotAllowedError,
)
from app.infrastructure.storage.minio import ObjectStorageError
from app.domain.users import User
from app.services.usage import UsageLimitExceededError


router = APIRouter(tags=["documents"])
_READ_CHUNK_BYTES = 1024 * 1024


class DocumentServicePort(Protocol):
    async def upload(self, **kwargs: object) -> DocumentSubmission: ...

    async def replace_document(self, document_id: UUID, **kwargs: object) -> DocumentSubmission: ...

    async def retry_version(self, document_id: UUID, version_id: UUID, **kwargs: object) -> DocumentSubmission: ...

    async def list_documents(self, space_id: UUID, **kwargs: object) -> list[StoredDocument]: ...

    async def search_documents(self, space_id: UUID, **kwargs: object) -> list[StoredDocument]: ...

    async def get_document(self, document_id: UUID, **kwargs: object) -> StoredDocument: ...

    async def retry(self, document_id: UUID, **kwargs: object): ...  # type: ignore[no-untyped-def]

    async def delete(self, document_id: UUID, **kwargs: object) -> StoredDocument: ...

    async def update_availability(self, document_id: UUID, **kwargs: object) -> StoredDocument: ...


def get_document_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> DocumentServicePort:
    return request.app.state.document_service_factory(session)


class DocumentResponse(BaseModel):
    id: UUID
    space_id: UUID
    owner_user_id: UUID | None
    category_id: UUID | None
    original_filename: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    active_version_id: UUID | None
    failure_code: str | None
    failure_message: str | None
    is_enabled: bool
    effective_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, document: StoredDocument) -> "DocumentResponse":
        return cls(
            id=document.id,
            space_id=document.space_id,
            owner_user_id=document.owner_user_id,
            category_id=document.category_id,
            original_filename=document.original_filename,
            mime_type=document.mime_type,
            size_bytes=document.size_bytes,
            status=document.status,
            active_version_id=document.active_version_id,
            failure_code=(document.failure_code.value if document.failure_code else None),
            failure_message=document.failure_message,
            is_enabled=document.is_enabled,
            effective_at=document.effective_at,
            expires_at=document.expires_at,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


class DocumentSubmissionResponse(BaseModel):
    document: DocumentResponse
    version_id: UUID
    processing_enqueued: bool

    @classmethod
    def from_domain(cls, submission: DocumentSubmission) -> "DocumentSubmissionResponse":
        return cls(
            document=DocumentResponse.from_domain(submission.document),
            version_id=submission.version.id,
            processing_enqueued=submission.processing_enqueued,
        )


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]


class DocumentBatchFailureResponse(BaseModel):
    filename: str
    code: str
    message: str


class DocumentBatchSubmissionResponse(BaseModel):
    items: list[DocumentSubmissionResponse]
    failures: list[DocumentBatchFailureResponse]


class DocumentRetryResponse(BaseModel):
    document: DocumentResponse
    version_id: UUID


async def _read_upload_limited(upload: UploadFile, *, maximum: int) -> bytes:
    parts: list[bytes] = []
    total = 0
    try:
        while chunk := await upload.read(_READ_CHUNK_BYTES):
            total += len(chunk)
            if total > maximum:
                raise DocumentUploadError("文件超过当前单文件大小上限。")
            parts.append(chunk)
    finally:
        await upload.close()
    return b"".join(parts)


def _translate_document_error(error: Exception) -> None:
    if isinstance(error, DocumentVersionConflictError):
        raise AppError(code='DOCUMENT_VERSION_CONFLICT', message=str(error), status_code=409) from error
    if isinstance(error, UsageLimitExceededError):
        raise AppError(code="USAGE_LIMIT_EXCEEDED", message=str(error), status_code=429) from error
    if isinstance(error, DocumentPermissionDeniedError):
        raise AppError(code="DOCUMENT_ACCESS_DENIED", message=str(error), status_code=403) from error
    if isinstance(error, DocumentUploadError):
        raise AppError(code="DOCUMENT_UPLOAD_INVALID", message=str(error), status_code=422) from error
    if isinstance(error, DocumentAlreadyExistsError):
        raise AppError(code="DOCUMENT_DUPLICATE", message=str(error), status_code=409) from error
    if isinstance(error, DocumentScopeError):
        raise AppError(code="DOCUMENT_SCOPE_INVALID", message="文档所属的空间或分类不存在。", status_code=404) from error
    if isinstance(error, DocumentNotFoundError):
        raise AppError(code="DOCUMENT_NOT_FOUND", message="文档不存在。", status_code=404) from error
    if isinstance(error, DocumentRetryNotAllowedError):
        raise AppError(code="DOCUMENT_RETRY_NOT_ALLOWED", message=str(error), status_code=409) from error
    from app.domain.documents import DocumentAvailabilityError
    if isinstance(error, DocumentAvailabilityError):
        raise AppError(code="DOCUMENT_AVAILABILITY_INVALID", message=str(error), status_code=422) from error
    raise error


@router.post('/documents/{document_id}/versions/{version_id}/retry', response_model=DocumentSubmissionResponse, status_code=202)
async def retry_document_version(document_id: UUID, version_id: UUID,
    service: DocumentServicePort = Depends(get_document_service), user: User = Depends(get_current_user)) -> DocumentSubmissionResponse:
    try:
        return DocumentSubmissionResponse.from_domain(await service.retry_version(document_id, version_id, owner_user_id=user.id))
    except Exception as error:
        _translate_document_error(error)
        raise


@router.post('/documents/{document_id}/versions', response_model=DocumentSubmissionResponse, status_code=202)
async def upload_document_version(document_id: UUID, request: Request, file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(get_current_user)], service=Depends(get_document_service)):
    try:
        content = await _read_upload_limited(file, maximum=request.app.state.settings.document_max_file_bytes)
        result = await service.replace_document(document_id, filename=file.filename or '', content=content,
            content_type=file.content_type, owner_user_id=user.id)
    except Exception as error:
        _translate_document_error(error)
        raise
    return DocumentSubmissionResponse.from_domain(result)


@router.post(
    "/spaces/{space_id}/documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentSubmissionResponse,
)
async def upload_document(
    space_id: UUID,
    request: Request,
    file: Annotated[UploadFile, File()],
    category_id: Annotated[UUID | None, Form()] = None,
    is_enabled: Annotated[bool, Form()] = True,
    effective_at: Annotated[datetime | None, Form()] = None,
    expires_at: Annotated[datetime | None, Form()] = None,
    service: DocumentServicePort = Depends(get_document_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> DocumentSubmissionResponse:
    # The optional request parameter is only used to read the configured limit
    # while keeping the service itself HTTP-independent.
    try:
        content = await _read_upload_limited(
            file, maximum=request.app.state.settings.document_max_file_bytes
        )
        upload_kwargs: dict[str, object] = {
            "space_id": space_id,
            "category_id": category_id,
            "filename": file.filename or "",
            "content": content,
            "content_type": file.content_type,
        }
        if not is_enabled:
            upload_kwargs["is_enabled"] = False
        if effective_at is not None:
            upload_kwargs["effective_at"] = effective_at
        if expires_at is not None:
            upload_kwargs["expires_at"] = expires_at
        if _current_user is not None:
            upload_kwargs["owner_user_id"] = _current_user.id
        submission = await service.upload(**upload_kwargs)
    except Exception as error:
        _translate_document_error(error)
        raise
    return DocumentSubmissionResponse.from_domain(submission)


@router.post(
    "/spaces/{space_id}/documents/batch",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentBatchSubmissionResponse,
)
async def upload_documents_batch(
    space_id: UUID,
    request: Request,
    files: Annotated[list[UploadFile], File()],
    category_id: Annotated[UUID | None, Form()] = None,
    is_enabled: Annotated[bool, Form()] = True,
    effective_at: Annotated[datetime | None, Form()] = None,
    expires_at: Annotated[datetime | None, Form()] = None,
    service: DocumentServicePort = Depends(get_document_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> DocumentBatchSubmissionResponse:
    """Upload up to twenty documents and report partial failures per file."""

    if not files or len(files) > 20:
        raise AppError(
            code="DOCUMENT_UPLOAD_INVALID",
            message="批量上传一次最多包含 20 个文件。",
            status_code=422,
        )
    items: list[DocumentSubmissionResponse] = []
    failures: list[DocumentBatchFailureResponse] = []
    for file in files:
        filename = file.filename or ""
        try:
            content = await _read_upload_limited(
                file, maximum=request.app.state.settings.document_max_file_bytes
            )
            upload_kwargs: dict[str, object] = {
                "space_id": space_id,
                "category_id": category_id,
                "filename": filename,
                "content": content,
                "content_type": file.content_type,
            }
            if not is_enabled:
                upload_kwargs["is_enabled"] = False
            if effective_at is not None:
                upload_kwargs["effective_at"] = effective_at
            if expires_at is not None:
                upload_kwargs["expires_at"] = expires_at
            if _current_user is not None:
                upload_kwargs["owner_user_id"] = _current_user.id
            submission = await service.upload(**upload_kwargs)
            items.append(DocumentSubmissionResponse.from_domain(submission))
        except Exception as error:
            if isinstance(error, UsageLimitExceededError):
                code, message = "USAGE_LIMIT_EXCEEDED", str(error)
            elif isinstance(error, DocumentPermissionDeniedError):
                code, message = "DOCUMENT_ACCESS_DENIED", str(error)
            elif isinstance(error, DocumentUploadError):
                code, message = "DOCUMENT_UPLOAD_INVALID", str(error)
            elif isinstance(error, DocumentAlreadyExistsError):
                code, message = "DOCUMENT_DUPLICATE", str(error)
            elif isinstance(error, DocumentScopeError):
                code, message = "DOCUMENT_SCOPE_INVALID", "文档所属的空间或分类不存在。"
            else:
                code, message = "DOCUMENT_UPLOAD_FAILED", "该文件上传失败，请稍后重试。"
            failures.append(
                DocumentBatchFailureResponse(filename=filename, code=code, message=message)
            )
    return DocumentBatchSubmissionResponse(items=items, failures=failures)


@router.get("/spaces/{space_id}/documents", response_model=DocumentListResponse)
async def list_documents(
    space_id: UUID,
    service: DocumentServicePort = Depends(get_document_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> DocumentListResponse:
    try:
        if _current_user is None:
            documents = await service.list_documents(space_id)
        else:
            documents = await service.list_documents(space_id, owner_user_id=_current_user.id)
    except Exception as error:
        _translate_document_error(error)
        raise
    return DocumentListResponse(items=[DocumentResponse.from_domain(item) for item in documents])


@router.get("/spaces/{space_id}/documents/search", response_model=DocumentListResponse)
async def search_documents(
    space_id: UUID,
    query: str = "",
    tag_id: UUID | None = None,
    service: DocumentServicePort = Depends(get_document_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> DocumentListResponse:
    try:
        if _current_user is None:
            documents = await service.search_documents(space_id, query=query, tag_id=tag_id)
        else:
            documents = await service.search_documents(
                space_id, query=query, tag_id=tag_id, owner_user_id=_current_user.id
            )
    except Exception as error:
        _translate_document_error(error)
        raise
    return DocumentListResponse(items=[DocumentResponse.from_domain(item) for item in documents])


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    service: DocumentServicePort = Depends(get_document_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> DocumentResponse:
    try:
        if _current_user is None:
            document = await service.get_document(document_id)
        else:
            document = await service.get_document(document_id, owner_user_id=_current_user.id)
    except Exception as error:
        _translate_document_error(error)
        raise
    return DocumentResponse.from_domain(document)


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: UUID,
    request: Request,
    service: DocumentServicePort = Depends(get_document_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> StreamingResponse:
    try:
        if _current_user is None:
            document = await service.get_document(document_id)
        else:
            document = await service.get_document(document_id, owner_user_id=_current_user.id)
        content = await request.app.state.storage.get_bytes(document.storage_key)
    except ObjectStorageError as error:
        raise AppError(
            code="DOCUMENT_DOWNLOAD_UNAVAILABLE",
            message="原文件暂时无法下载，请稍后重试。",
            status_code=503,
        ) from error
    except Exception as error:
        _translate_document_error(error)
        raise
    filename = quote(document.original_filename, safe="")
    return StreamingResponse(
        iter((content,)),
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/documents/{document_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentRetryResponse,
)
async def retry_document(
    document_id: UUID,
    service: DocumentServicePort = Depends(get_document_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> DocumentRetryResponse:
    try:
        if _current_user is None:
            document, version = await service.retry(document_id)
        else:
            document, version = await service.retry(document_id, owner_user_id=_current_user.id)
    except Exception as error:
        _translate_document_error(error)
        raise
    return DocumentRetryResponse(
        document=DocumentResponse.from_domain(document), version_id=version.id
    )


class DocumentAvailabilityRequest(BaseModel):
    is_enabled: bool | None = None
    effective_at: datetime | None = None
    expires_at: datetime | None = None


@router.patch("/documents/{document_id}/availability", response_model=DocumentResponse)
async def update_document_availability(
    document_id: UUID,
    payload: DocumentAvailabilityRequest,
    service: DocumentServicePort = Depends(get_document_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> DocumentResponse:
    try:
        if _current_user is None:
            current = await service.get_document(document_id)
        else:
            current = await service.get_document(document_id, owner_user_id=_current_user.id)
        changes = payload.model_dump(exclude_unset=True)
        if "effective_at" not in changes:
            changes["effective_at"] = current.effective_at
        if "expires_at" not in changes:
            changes["expires_at"] = current.expires_at
        if "is_enabled" not in changes:
            changes["is_enabled"] = current.is_enabled
        if _current_user is not None:
            changes["owner_user_id"] = _current_user.id
        updated = await service.update_availability(document_id, **changes)
    except Exception as error:
        _translate_document_error(error)
        raise
    return DocumentResponse.from_domain(updated)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    service: DocumentServicePort = Depends(get_document_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
):
    try:
        if _current_user is None:
            await service.delete(document_id)
        else:
            await service.delete(document_id, owner_user_id=_current_user.id)
    except Exception as error:
        _translate_document_error(error)
        raise
    from fastapi import Response

    return Response(status_code=status.HTTP_204_NO_CONTENT)
