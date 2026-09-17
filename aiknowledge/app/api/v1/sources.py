from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session, get_optional_current_user
from app.core.errors import AppError
from app.domain.sources import KnowledgeSource, SourceKind, SourceStatus, SourceSyncResult
from app.domain.users import User
from app.services.sources import SourceAccessDeniedError, SourceNotFoundError, SourceSyncError


router = APIRouter(tags=["sources"])


class SourceServicePort(Protocol):
    async def list_sources(self, space_id: UUID, **kwargs: object) -> list[KnowledgeSource]: ...

    async def create_source(self, **kwargs: object) -> KnowledgeSource: ...

    async def set_status(self, source_id: UUID, **kwargs: object) -> KnowledgeSource: ...

    async def sync_source(self, source_id: UUID, **kwargs: object) -> SourceSyncResult: ...


def get_source_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> SourceServicePort:
    return request.app.state.source_service_factory(session)


class SourceRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: SourceKind
    locator: str = Field(min_length=1, max_length=2_000)
    name: str | None = Field(default=None, max_length=120)


class SourceStatusRequest(BaseModel):
    status: SourceStatus


class SourceResponse(BaseModel):
    id: UUID
    space_id: UUID
    kind: SourceKind
    locator: str
    name: str | None
    status: SourceStatus
    last_checksum: str | None
    last_synced_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, source: KnowledgeSource) -> "SourceResponse":
        return cls(
            id=source.id,
            space_id=source.space_id,
            kind=source.kind,
            locator=source.locator,
            name=source.name,
            status=source.status,
            last_checksum=source.last_checksum,
            last_synced_at=source.last_synced_at,
            last_error=source.last_error,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )


class SourceListResponse(BaseModel):
    items: list[SourceResponse]


class SourceSyncResponse(BaseModel):
    source: SourceResponse
    uploaded: int
    failed: int
    skipped: bool

    @classmethod
    def from_domain(cls, result: SourceSyncResult) -> "SourceSyncResponse":
        return cls(
            source=SourceResponse.from_domain(result.source),
            uploaded=result.uploaded,
            failed=result.failed,
            skipped=result.skipped,
        )


def _translate_source_error(error: Exception) -> None:
    if isinstance(error, SourceAccessDeniedError):
        raise AppError(code="SOURCE_ACCESS_DENIED", message=str(error), status_code=403) from error
    if isinstance(error, SourceNotFoundError):
        raise AppError(code="SOURCE_NOT_FOUND", message="知识来源不存在。", status_code=404) from error
    if isinstance(error, SourceSyncError):
        raise AppError(code="SOURCE_SYNC_FAILED", message=str(error), status_code=409) from error
    if isinstance(error, ValueError):
        raise AppError(code="SOURCE_INVALID", message=str(error), status_code=422) from error
    raise error


@router.get("/spaces/{space_id}/sources", response_model=SourceListResponse)
async def list_sources(
    space_id: UUID,
    service: SourceServicePort = Depends(get_source_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> SourceListResponse:
    try:
        kwargs = {"owner_user_id": _current_user.id} if _current_user is not None else {}
        items = await service.list_sources(space_id, **kwargs)
    except Exception as error:
        _translate_source_error(error)
        raise
    return SourceListResponse(items=[SourceResponse.from_domain(item) for item in items])


@router.post(
    "/spaces/{space_id}/sources",
    status_code=status.HTTP_201_CREATED,
    response_model=SourceResponse,
)
async def create_source(
    space_id: UUID,
    payload: SourceRequest,
    service: SourceServicePort = Depends(get_source_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> SourceResponse:
    try:
        kwargs: dict[str, object] = {
            "space_id": space_id,
            **payload.model_dump(),
        }
        if _current_user is not None:
            kwargs["owner_user_id"] = _current_user.id
        source = await service.create_source(**kwargs)
    except Exception as error:
        _translate_source_error(error)
        raise
    return SourceResponse.from_domain(source)


@router.patch("/sources/{source_id}", response_model=SourceResponse)
async def update_source_status(
    source_id: UUID,
    payload: SourceStatusRequest,
    service: SourceServicePort = Depends(get_source_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> SourceResponse:
    try:
        kwargs: dict[str, object] = {"status": payload.status}
        if _current_user is not None:
            kwargs["owner_user_id"] = _current_user.id
        source = await service.set_status(source_id, **kwargs)
    except Exception as error:
        _translate_source_error(error)
        raise
    return SourceResponse.from_domain(source)


@router.post("/sources/{source_id}/sync", response_model=SourceSyncResponse)
async def sync_source(
    source_id: UUID,
    service: SourceServicePort = Depends(get_source_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> SourceSyncResponse:
    try:
        kwargs: dict[str, object] = {}
        if _current_user is not None:
            kwargs["owner_user_id"] = _current_user.id
        result = await service.sync_source(source_id, **kwargs)
    except Exception as error:
        _translate_source_error(error)
        raise
    return SourceSyncResponse.from_domain(result)
