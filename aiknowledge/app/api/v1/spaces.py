from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session
from app.core.errors import AppError
from app.domain.spaces import (
    Category,
    CategoryNotFoundError,
    CreatedShareLink,
    KnowledgeSpace,
    ShareLink,
    ShareLinkNotFoundError,
    SpaceNotFoundError,
    SpaceRuleViolationError,
    SpaceVisibility,
)


router = APIRouter(tags=["spaces"])


class SpaceServicePort(Protocol):
    async def list_spaces(self) -> list[KnowledgeSpace]: ...

    async def get_space(self, space_id: UUID) -> KnowledgeSpace: ...

    async def create_space(self, **kwargs: object) -> KnowledgeSpace: ...

    async def update_space(self, space_id: UUID, **kwargs: object) -> KnowledgeSpace: ...

    async def delete_space(self, space_id: UUID) -> KnowledgeSpace: ...

    async def list_categories(self, space_id: UUID) -> list[Category]: ...

    async def create_category(self, **kwargs: object) -> Category: ...

    async def update_category(self, category_id: UUID, **kwargs: object) -> Category: ...

    async def delete_category(self, category_id: UUID) -> Category: ...

    async def create_share_link(self, **kwargs: object) -> CreatedShareLink: ...

    async def list_share_links(self, space_id: UUID) -> list[ShareLink]: ...

    async def revoke_share_link(self, share_link_id: UUID) -> ShareLink: ...


def get_space_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> SpaceServicePort:
    return request.app.state.space_service_factory(session)


class SpaceCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    visibility: SpaceVisibility = SpaceVisibility.PRIVATE
    guest_feedback_enabled: bool = False


class SpaceUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    visibility: SpaceVisibility | None = None
    guest_feedback_enabled: bool | None = None


class SpaceResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    visibility: SpaceVisibility
    guest_feedback_enabled: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, space: KnowledgeSpace) -> "SpaceResponse":
        return cls(
            id=space.id,
            name=space.name,
            description=space.description,
            visibility=space.visibility,
            guest_feedback_enabled=space.guest_feedback_enabled,
            created_at=space.created_at,
            updated_at=space.updated_at,
        )


class SpaceListResponse(BaseModel):
    items: list[SpaceResponse]


class CategoryCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_open: bool = False
    sort_order: int = Field(default=0, ge=0, le=10_000)


class CategoryUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_open: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)


class CategoryResponse(BaseModel):
    id: UUID
    space_id: UUID
    name: str
    description: str | None
    is_open: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, category: Category) -> "CategoryResponse":
        return cls(
            id=category.id,
            space_id=category.space_id,
            name=category.name,
            description=category.description,
            is_open=category.is_open,
            sort_order=category.sort_order,
            created_at=category.created_at,
            updated_at=category.updated_at,
        )


class CategoryListResponse(BaseModel):
    items: list[CategoryResponse]


class ShareLinkCreateRequest(BaseModel):
    category_ids: list[UUID] = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None


class ShareLinkResponse(BaseModel):
    id: UUID
    space_id: UUID
    category_ids: list[UUID]
    status: str
    created_at: datetime
    revoked_at: datetime | None
    expires_at: datetime | None

    @classmethod
    def from_domain(cls, link: ShareLink) -> "ShareLinkResponse":
        return cls(
            id=link.id,
            space_id=link.space_id,
            category_ids=list(link.category_ids),
            status=link.status.value,
            created_at=link.created_at,
            revoked_at=link.revoked_at,
            expires_at=link.expires_at,
        )


class CreatedShareLinkResponse(BaseModel):
    link: ShareLinkResponse
    token: str

    @classmethod
    def from_domain(cls, created: CreatedShareLink) -> "CreatedShareLinkResponse":
        return cls(link=ShareLinkResponse.from_domain(created.link), token=created.token)


class ShareLinkListResponse(BaseModel):
    items: list[ShareLinkResponse]


def _translate_space_error(error: Exception) -> None:
    if isinstance(error, SpaceNotFoundError):
        raise AppError(
            code="SPACE_NOT_FOUND", message="知识空间不存在。", status_code=404
        ) from error
    if isinstance(error, CategoryNotFoundError):
        raise AppError(code="CATEGORY_NOT_FOUND", message="分类不存在。", status_code=404) from error
    if isinstance(error, ShareLinkNotFoundError):
        raise AppError(code="SHARE_LINK_NOT_FOUND", message="分享链接不存在。", status_code=404) from error
    if isinstance(error, SpaceRuleViolationError):
        raise AppError(
            code="SPACE_RULE_VIOLATION", message=str(error), status_code=409
        ) from error
    raise error


@router.get("/spaces", response_model=SpaceListResponse)
async def list_spaces(
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> SpaceListResponse:
    return SpaceListResponse(items=[SpaceResponse.from_domain(item) for item in await service.list_spaces()])


@router.post("/spaces", status_code=status.HTTP_201_CREATED, response_model=SpaceResponse)
async def create_space(
    payload: SpaceCreateRequest,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> SpaceResponse:
    try:
        created = await service.create_space(
            name=payload.name,
            description=payload.description,
            visibility=payload.visibility,
            guest_feedback_enabled=payload.guest_feedback_enabled,
        )
    except Exception as error:
        _translate_space_error(error)
        raise
    return SpaceResponse.from_domain(created)


@router.get("/spaces/{space_id}", response_model=SpaceResponse)
async def get_space(
    space_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> SpaceResponse:
    try:
        space = await service.get_space(space_id)
    except Exception as error:
        _translate_space_error(error)
        raise
    return SpaceResponse.from_domain(space)


@router.patch("/spaces/{space_id}", response_model=SpaceResponse)
async def update_space(
    space_id: UUID,
    payload: SpaceUpdateRequest,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> SpaceResponse:
    changes: dict[str, object] = {}
    for field in ("name", "description", "visibility", "guest_feedback_enabled"):
        if field in payload.model_fields_set:
            changes[field] = getattr(payload, field)
    try:
        updated = await service.update_space(space_id, **changes)
    except Exception as error:
        _translate_space_error(error)
        raise
    return SpaceResponse.from_domain(updated)


@router.delete("/spaces/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_space(
    space_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> Response:
    try:
        await service.delete_space(space_id)
    except Exception as error:
        _translate_space_error(error)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/spaces/{space_id}/categories", response_model=CategoryListResponse)
async def list_categories(
    space_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> CategoryListResponse:
    try:
        categories = await service.list_categories(space_id)
    except Exception as error:
        _translate_space_error(error)
        raise
    return CategoryListResponse(items=[CategoryResponse.from_domain(item) for item in categories])


@router.post(
    "/spaces/{space_id}/categories",
    status_code=status.HTTP_201_CREATED,
    response_model=CategoryResponse,
)
async def create_category(
    space_id: UUID,
    payload: CategoryCreateRequest,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> CategoryResponse:
    try:
        category = await service.create_category(space_id=space_id, **payload.model_dump())
    except Exception as error:
        _translate_space_error(error)
        raise
    return CategoryResponse.from_domain(category)


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: UUID,
    payload: CategoryUpdateRequest,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> CategoryResponse:
    changes = {
        field: getattr(payload, field)
        for field in ("name", "description", "is_open", "sort_order")
        if field in payload.model_fields_set
    }
    try:
        category = await service.update_category(category_id, **changes)
    except Exception as error:
        _translate_space_error(error)
        raise
    return CategoryResponse.from_domain(category)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> Response:
    try:
        await service.delete_category(category_id)
    except Exception as error:
        _translate_space_error(error)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/spaces/{space_id}/share-links", response_model=ShareLinkListResponse)
async def list_share_links(
    space_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> ShareLinkListResponse:
    try:
        links = await service.list_share_links(space_id)
    except Exception as error:
        _translate_space_error(error)
        raise
    return ShareLinkListResponse(items=[ShareLinkResponse.from_domain(item) for item in links])


@router.post(
    "/spaces/{space_id}/share-links",
    status_code=status.HTTP_201_CREATED,
    response_model=CreatedShareLinkResponse,
)
async def create_share_link(
    space_id: UUID,
    payload: ShareLinkCreateRequest,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> CreatedShareLinkResponse:
    try:
        created = await service.create_share_link(space_id=space_id, **payload.model_dump())
    except Exception as error:
        _translate_space_error(error)
        raise
    return CreatedShareLinkResponse.from_domain(created)


@router.delete("/share-links/{share_link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share_link(
    share_link_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
) -> Response:
    try:
        await service.revoke_share_link(share_link_id)
    except Exception as error:
        _translate_space_error(error)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)
