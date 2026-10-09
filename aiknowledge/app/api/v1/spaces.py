from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session, get_optional_current_user
from app.core.errors import AppError
from app.domain.spaces import (
    Category,
    CategoryNotFoundError,
    CreatedShareLink,
    KnowledgeSpace,
    ShareLink,
    ShareLinkNotFoundError,
    SpaceAccessDeniedError,
    SpaceNotFoundError,
    SpaceRuleViolationError,
    SpacePlan,
    SpaceKind,
    SpaceVisibility,
    PublicQuestionRecord,
)
from app.domain.public_answers import PublicContentMode
from app.domain.users import User
from app.services.public_questions import (
    PublicQuestionLogAccessDeniedError,
    PublicQuestionLogNotFoundError,
)


router = APIRouter(tags=["spaces"])


class SpaceServicePort(Protocol):
    async def list_spaces(self, owner_user_id: UUID | None = None) -> list[KnowledgeSpace]: ...

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


class PublicQuestionLogServicePort(Protocol):
    async def list_questions(
        self,
        space_id: UUID,
        *,
        owner_user_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PublicQuestionRecord]: ...


def get_space_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> SpaceServicePort:
    return request.app.state.space_service_factory(session)


def get_public_question_log_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> PublicQuestionLogServicePort:
    return request.app.state.public_question_log_service_factory(session)


class SpaceCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    visibility: SpaceVisibility = SpaceVisibility.PRIVATE
    kind: SpaceKind = SpaceKind.PERSONAL
    guest_feedback_enabled: bool = False


class SpaceUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    visibility: SpaceVisibility | None = None
    guest_feedback_enabled: bool | None = None
    plan: SpacePlan | None = None


class SpaceResponse(BaseModel):
    id: UUID
    owner_user_id: UUID | None
    name: str
    description: str | None
    visibility: SpaceVisibility
    guest_feedback_enabled: bool
    plan: SpacePlan
    kind: SpaceKind
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, space: KnowledgeSpace) -> "SpaceResponse":
        return cls(
            id=space.id,
            owner_user_id=space.owner_user_id,
            name=space.name,
            description=space.description,
            visibility=space.visibility,
            guest_feedback_enabled=space.guest_feedback_enabled,
            plan=space.plan,
            kind=space.kind,
            created_at=space.created_at,
            updated_at=space.updated_at,
        )


class SpaceListResponse(BaseModel):
    items: list[SpaceResponse]


class PublicQuestionRecordResponse(BaseModel):
    id: UUID
    share_link_id: UUID
    visitor_id: str
    conversation_id: UUID | None
    question_hash: str
    created_at: datetime
    is_hidden: bool
    moderation_note: str | None
    moderated_at: datetime | None

    @classmethod
    def from_domain(cls, record: PublicQuestionRecord) -> "PublicQuestionRecordResponse":
        return cls(
            id=record.id,
            share_link_id=record.share_link_id,
            visitor_id=record.visitor_id,
            conversation_id=record.conversation_id,
            question_hash=record.question_hash,
            created_at=record.created_at,
            is_hidden=record.is_hidden,
            moderation_note=record.moderation_note,
            moderated_at=record.moderated_at,
        )


class PublicQuestionRecordListResponse(BaseModel):
    items: list[PublicQuestionRecordResponse]


class CategoryCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    display_name: str | None = Field(default=None, max_length=120)
    display_description: str | None = Field(default=None, max_length=2000)
    is_open: bool = False
    sort_order: int = Field(default=0, ge=0, le=10_000)
    is_default: bool = False


class CategoryUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    display_name: str | None = Field(default=None, max_length=120)
    display_description: str | None = Field(default=None, max_length=2000)
    is_open: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    is_default: bool | None = None


class CategoryResponse(BaseModel):
    id: UUID
    space_id: UUID
    name: str
    description: str | None
    display_name: str | None
    display_description: str | None
    is_open: bool
    sort_order: int
    is_default: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, category: Category) -> "CategoryResponse":
        return cls(
            id=category.id,
            space_id=category.space_id,
            name=category.name,
            description=category.description,
            display_name=category.display_name,
            display_description=category.display_description,
            is_open=category.is_open,
            sort_order=category.sort_order,
            is_default=category.is_default,
            created_at=category.created_at,
            updated_at=category.updated_at,
        )


class CategoryListResponse(BaseModel):
    items: list[CategoryResponse]


class ShareLinkCreateRequest(BaseModel):
    category_ids: list[UUID] = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None
    password: str | None = Field(default=None, min_length=4, max_length=128)
    visitor_question_limit: int | None = Field(default=None, ge=1, le=100_000)
    allowed_origins: list[str] = Field(default_factory=list, max_length=10)
    content_mode: PublicContentMode = PublicContentMode.DOCUMENTS


class ShareLinkResponse(BaseModel):
    id: UUID
    space_id: UUID
    category_ids: list[UUID]
    status: str
    created_at: datetime
    revoked_at: datetime | None
    expires_at: datetime | None
    visitor_question_limit: int | None
    allowed_origins: list[str]
    content_mode: PublicContentMode

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
            visitor_question_limit=link.visitor_question_limit,
            allowed_origins=list(link.allowed_origins),
            content_mode=link.content_mode,
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
    if isinstance(error, SpaceAccessDeniedError):
        raise AppError(
            code="SPACE_ACCESS_DENIED", message=str(error), status_code=403
        ) from error
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
    if isinstance(error, PublicQuestionLogAccessDeniedError):
        raise AppError(
            code="SPACE_ACCESS_DENIED", message=str(error), status_code=403
        ) from error
    if isinstance(error, PublicQuestionLogNotFoundError):
        raise AppError(
            code="SPACE_NOT_FOUND", message="知识空间不存在。", status_code=404
        ) from error
    raise error


@router.get("/spaces", response_model=SpaceListResponse)
async def list_spaces(
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> SpaceListResponse:
    if current_user is None:
        spaces = await service.list_spaces()
    else:
        spaces = await service.list_spaces(owner_user_id=current_user.id)
    return SpaceListResponse(items=[SpaceResponse.from_domain(item) for item in spaces])


@router.get(
    "/spaces/{space_id}/public-questions",
    response_model=PublicQuestionRecordListResponse,
)
async def list_public_questions(
    space_id: UUID,
    service: Annotated[PublicQuestionLogServicePort, Depends(get_public_question_log_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PublicQuestionRecordListResponse:
    try:
        records = await service.list_questions(
            space_id,
            **({"owner_user_id": current_user.id} if current_user is not None else {}),
            limit=limit,
            offset=offset,
        )
    except Exception as error:
        _translate_space_error(error)
        raise
    return PublicQuestionRecordListResponse(
        items=[PublicQuestionRecordResponse.from_domain(item) for item in records]
    )


@router.post("/spaces", status_code=status.HTTP_201_CREATED, response_model=SpaceResponse)
async def create_space(
    payload: SpaceCreateRequest,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> SpaceResponse:
    kwargs = payload.model_dump()
    if current_user is not None:
        kwargs["owner_user_id"] = current_user.id
    try:
        created = await service.create_space(**kwargs)
    except Exception as error:
        _translate_space_error(error)
        raise
    return SpaceResponse.from_domain(created)


@router.get("/spaces/{space_id}", response_model=SpaceResponse)
async def get_space(
    space_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> SpaceResponse:
    try:
        if current_user is None:
            space = await service.get_space(space_id)
        else:
            space = await service.get_space(space_id, owner_user_id=current_user.id)
    except Exception as error:
        _translate_space_error(error)
        raise
    return SpaceResponse.from_domain(space)


@router.patch("/spaces/{space_id}", response_model=SpaceResponse)
async def update_space(
    space_id: UUID,
    payload: SpaceUpdateRequest,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> SpaceResponse:
    changes: dict[str, object] = {}
    for field in ("name", "description", "visibility", "guest_feedback_enabled", "plan"):
        if field in payload.model_fields_set:
            changes[field] = getattr(payload, field)
    try:
        if current_user is None:
            updated = await service.update_space(space_id, **changes)
        else:
            updated = await service.update_space(space_id, owner_user_id=current_user.id, **changes)
    except Exception as error:
        _translate_space_error(error)
        raise
    return SpaceResponse.from_domain(updated)


@router.delete("/spaces/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_space(
    space_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> Response:
    try:
        if current_user is None:
            await service.delete_space(space_id)
        else:
            await service.delete_space(space_id, owner_user_id=current_user.id)
    except Exception as error:
        _translate_space_error(error)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/spaces/{space_id}/categories", response_model=CategoryListResponse)
async def list_categories(
    space_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> CategoryListResponse:
    try:
        if current_user is None:
            categories = await service.list_categories(space_id)
        else:
            categories = await service.list_categories(space_id, owner_user_id=current_user.id)
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
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> CategoryResponse:
    try:
        kwargs = payload.model_dump()
        kwargs["space_id"] = space_id
        if current_user is not None:
            kwargs["owner_user_id"] = current_user.id
        category = await service.create_category(**kwargs)
    except Exception as error:
        _translate_space_error(error)
        raise
    return CategoryResponse.from_domain(category)


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: UUID,
    payload: CategoryUpdateRequest,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> CategoryResponse:
    changes = {
        field: getattr(payload, field)
        for field in (
            "name",
            "description",
            "display_name",
            "display_description",
            "is_open",
            "sort_order",
            "is_default",
        )
        if field in payload.model_fields_set
    }
    try:
        if current_user is None:
            category = await service.update_category(category_id, **changes)
        else:
            category = await service.update_category(category_id, owner_user_id=current_user.id, **changes)
    except Exception as error:
        _translate_space_error(error)
        raise
    return CategoryResponse.from_domain(category)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> Response:
    try:
        if current_user is None:
            await service.delete_category(category_id)
        else:
            await service.delete_category(category_id, owner_user_id=current_user.id)
    except Exception as error:
        _translate_space_error(error)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/spaces/{space_id}/share-links", response_model=ShareLinkListResponse)
async def list_share_links(
    space_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> ShareLinkListResponse:
    try:
        if current_user is None:
            links = await service.list_share_links(space_id)
        else:
            links = await service.list_share_links(space_id, owner_user_id=current_user.id)
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
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> CreatedShareLinkResponse:
    try:
        kwargs = payload.model_dump()
        kwargs["space_id"] = space_id
        if current_user is not None:
            kwargs["owner_user_id"] = current_user.id
        created = await service.create_share_link(**kwargs)
    except Exception as error:
        _translate_space_error(error)
        raise
    return CreatedShareLinkResponse.from_domain(created)


@router.delete("/share-links/{share_link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share_link(
    share_link_id: UUID,
    service: Annotated[SpaceServicePort, Depends(get_space_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> Response:
    try:
        if current_user is None:
            await service.revoke_share_link(share_link_id)
        else:
            await service.revoke_share_link(share_link_id, owner_user_id=current_user.id)
    except Exception as error:
        _translate_space_error(error)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)
