from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session, get_optional_current_user
from app.core.errors import AppError
from app.domain.tags import (
    KnowledgeTag,
    TagNameConflictError,
    TagPermissionDeniedError,
    TagNotFoundError,
    TagValidationError,
)
from app.domain.users import User


router = APIRouter(tags=["tags"])


class TagServicePort(Protocol):
    async def list_tags(self, space_id: UUID, **kwargs: object) -> list[KnowledgeTag]: ...

    async def create_tag(self, *, space_id: UUID, name: str, color: str | None = None, **kwargs: object) -> KnowledgeTag: ...

    async def update_tag(self, tag_id: UUID, *, name: str | None = None, color: str | None = None, **kwargs: object) -> KnowledgeTag: ...

    async def delete_tag(self, tag_id: UUID, **kwargs: object) -> None: ...

    async def set_document_tags(self, *, document_id: UUID, tag_ids: tuple[UUID, ...], space_id: UUID, **kwargs: object) -> tuple[KnowledgeTag, ...]: ...

    async def get_document_tags(self, document_id: UUID, **kwargs: object) -> tuple[KnowledgeTag, ...]: ...


def get_tag_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> TagServicePort:
    return request.app.state.tag_service_factory(session)


class TagRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=7)


class TagResponse(BaseModel):
    id: UUID
    space_id: UUID
    name: str
    color: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, tag: KnowledgeTag) -> "TagResponse":
        return cls(
            id=tag.id,
            space_id=tag.space_id,
            name=tag.name,
            color=tag.color,
            created_at=tag.created_at,
            updated_at=tag.updated_at,
        )


class TagListResponse(BaseModel):
    items: list[TagResponse]


class DocumentTagsRequest(BaseModel):
    tag_ids: list[UUID] = Field(default_factory=list, max_length=100)


class DocumentTagsResponse(BaseModel):
    items: list[TagResponse]


def _translate_tag_error(error: Exception) -> None:
    if isinstance(error, TagPermissionDeniedError):
        raise AppError(code="TAG_ACCESS_DENIED", message=str(error), status_code=403) from error
    if isinstance(error, TagNotFoundError):
        raise AppError(code="TAG_NOT_FOUND", message="标签不存在。", status_code=404) from error
    if isinstance(error, (TagNameConflictError, TagValidationError, ValueError)):
        raise AppError(code="TAG_INVALID", message=str(error), status_code=422) from error
    raise error


@router.get("/spaces/{space_id}/tags", response_model=TagListResponse)
async def list_tags(
    space_id: UUID,
    service: TagServicePort = Depends(get_tag_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> TagListResponse:
    kwargs = {"owner_user_id": _current_user.id} if _current_user is not None else {}
    return TagListResponse(items=[TagResponse.from_domain(tag) for tag in await service.list_tags(space_id, **kwargs)])


@router.post("/spaces/{space_id}/tags", status_code=status.HTTP_201_CREATED, response_model=TagResponse)
async def create_tag(
    space_id: UUID,
    payload: TagRequest,
    service: TagServicePort = Depends(get_tag_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> TagResponse:
    try:
        kwargs = {"owner_user_id": _current_user.id} if _current_user is not None else {}
        tag = await service.create_tag(space_id=space_id, **payload.model_dump(), **kwargs)
    except Exception as error:
        _translate_tag_error(error)
        raise
    return TagResponse.from_domain(tag)


@router.patch("/tags/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: UUID,
    payload: TagRequest,
    service: TagServicePort = Depends(get_tag_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> TagResponse:
    try:
        kwargs = {"owner_user_id": _current_user.id} if _current_user is not None else {}
        tag = await service.update_tag(tag_id, **payload.model_dump(), **kwargs)
    except Exception as error:
        _translate_tag_error(error)
        raise
    return TagResponse.from_domain(tag)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: UUID,
    service: TagServicePort = Depends(get_tag_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> None:
    try:
        kwargs = {"owner_user_id": _current_user.id} if _current_user is not None else {}
        await service.delete_tag(tag_id, **kwargs)
    except Exception as error:
        _translate_tag_error(error)
        raise


@router.put("/spaces/{space_id}/documents/{document_id}/tags", response_model=DocumentTagsResponse)
async def set_document_tags(
    space_id: UUID,
    document_id: UUID,
    payload: DocumentTagsRequest,
    service: TagServicePort = Depends(get_tag_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> DocumentTagsResponse:
    try:
        tags = await service.set_document_tags(
            document_id=document_id,
            tag_ids=tuple(payload.tag_ids),
            space_id=space_id,
            **({"owner_user_id": _current_user.id} if _current_user is not None else {}),
        )
    except Exception as error:
        _translate_tag_error(error)
        raise
    return DocumentTagsResponse(items=[TagResponse.from_domain(tag) for tag in tags])


@router.get("/documents/{document_id}/tags", response_model=DocumentTagsResponse)
async def get_document_tags(
    document_id: UUID,
    service: TagServicePort = Depends(get_tag_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> DocumentTagsResponse:
    return DocumentTagsResponse(
        items=[TagResponse.from_domain(tag) for tag in await service.get_document_tags(
            document_id,
            **({"owner_user_id": _current_user.id} if _current_user is not None else {}),
        )]
    )
