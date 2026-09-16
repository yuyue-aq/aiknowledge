from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session
from app.core.errors import AppError
from app.domain.documents import DocumentSubmission, DocumentStatus, StoredDocument
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


router = APIRouter(tags=["documents"])
_READ_CHUNK_BYTES = 1024 * 1024


class DocumentServicePort(Protocol):
    async def upload(self, **kwargs: object) -> DocumentSubmission: ...

    async def list_documents(self, space_id: UUID) -> list[StoredDocument]: ...

    async def get_document(self, document_id: UUID) -> StoredDocument: ...

    async def retry(self, document_id: UUID): ...  # type: ignore[no-untyped-def]

    async def delete(self, document_id: UUID) -> StoredDocument: ...


def get_document_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> DocumentServicePort:
    return request.app.state.document_service_factory(session)


class DocumentResponse(BaseModel):
    id: UUID
    space_id: UUID
    category_id: UUID | None
    original_filename: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    active_version_id: UUID | None
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, document: StoredDocument) -> "DocumentResponse":
        return cls(
            id=document.id,
            space_id=document.space_id,
            category_id=document.category_id,
            original_filename=document.original_filename,
            mime_type=document.mime_type,
            size_bytes=document.size_bytes,
            status=document.status,
            active_version_id=document.active_version_id,
            failure_code=(document.failure_code.value if document.failure_code else None),
            failure_message=document.failure_message,
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
    raise error


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
    service: DocumentServicePort = Depends(get_document_service),
) -> DocumentSubmissionResponse:
    # The optional request parameter is only used to read the configured limit
    # while keeping the service itself HTTP-independent.
    try:
        content = await _read_upload_limited(
            file, maximum=request.app.state.settings.document_max_file_bytes
        )
        submission = await service.upload(
            space_id=space_id,
            category_id=category_id,
            filename=file.filename or "",
            content=content,
            content_type=file.content_type,
        )
    except Exception as error:
        _translate_document_error(error)
        raise
    return DocumentSubmissionResponse.from_domain(submission)


@router.get("/spaces/{space_id}/documents", response_model=DocumentListResponse)
async def list_documents(
    space_id: UUID,
    service: DocumentServicePort = Depends(get_document_service),
) -> DocumentListResponse:
    try:
        documents = await service.list_documents(space_id)
    except Exception as error:
        _translate_document_error(error)
        raise
    return DocumentListResponse(items=[DocumentResponse.from_domain(item) for item in documents])


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    service: DocumentServicePort = Depends(get_document_service),
) -> DocumentResponse:
    try:
        document = await service.get_document(document_id)
    except Exception as error:
        _translate_document_error(error)
        raise
    return DocumentResponse.from_domain(document)


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: UUID,
    request: Request,
    service: DocumentServicePort = Depends(get_document_service),
) -> StreamingResponse:
    try:
        document = await service.get_document(document_id)
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
) -> DocumentRetryResponse:
    try:
        document, version = await service.retry(document_id)
    except Exception as error:
        _translate_document_error(error)
        raise
    return DocumentRetryResponse(
        document=DocumentResponse.from_domain(document), version_id=version.id
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    service: DocumentServicePort = Depends(get_document_service),
):
    try:
        await service.delete(document_id)
    except Exception as error:
        _translate_document_error(error)
        raise
    from fastapi import Response

    return Response(status_code=status.HTTP_204_NO_CONTENT)
