from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_database_session
from app.core.errors import AppError
from app.domain.users import (
    SpaceMembership,
    SpaceRole,
    User,
    UserNotFoundError,
)
from app.services.memberships import (
    MembershipAccessDeniedError,
    MembershipAlreadyExistsError,
)
from app.services.usage import UsageLimitExceededError


router = APIRouter(tags=["memberships"])


class MembershipServicePort(Protocol):
    async def list_members(self, *, space_id: UUID, actor_user_id: UUID) -> list[SpaceMembership]: ...

    async def add_member(self, *, space_id: UUID, actor_user_id: UUID, email: str, role: SpaceRole) -> SpaceMembership: ...

    async def change_role(self, *, space_id: UUID, actor_user_id: UUID, member_user_id: UUID, role: SpaceRole) -> SpaceMembership: ...

    async def remove_member(self, *, space_id: UUID, actor_user_id: UUID, member_user_id: UUID) -> None: ...

    async def get_user(self, user_id: UUID) -> User: ...


def get_membership_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> MembershipServicePort:
    return request.app.state.membership_service_factory(session)


class MemberCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    role: SpaceRole = SpaceRole.MEMBER


class MemberRoleRequest(BaseModel):
    role: SpaceRole


class MemberResponse(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    role: SpaceRole
    created_at: datetime

    @classmethod
    def from_domain(cls, membership: SpaceMembership, user: User) -> "MemberResponse":
        return cls(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=membership.role,
            created_at=membership.created_at,
        )


def _translate_membership_error(error: Exception) -> None:
    if isinstance(error, UsageLimitExceededError):
        raise AppError(code="USAGE_LIMIT_EXCEEDED", message=str(error), status_code=429) from error
    if isinstance(error, MembershipAccessDeniedError):
        raise AppError(code="MEMBERSHIP_ACCESS_DENIED", message=str(error), status_code=403) from error
    if isinstance(error, MembershipAlreadyExistsError):
        raise AppError(code="MEMBER_ALREADY_EXISTS", message=str(error), status_code=409) from error
    if isinstance(error, UserNotFoundError):
        raise AppError(code="MEMBER_NOT_FOUND", message=str(error), status_code=404) from error
    raise error


@router.get("/spaces/{space_id}/members", response_model=list[MemberResponse])
async def list_members(
    space_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MembershipServicePort, Depends(get_membership_service)],
) -> list[MemberResponse]:
    try:
        memberships = await service.list_members(space_id=space_id, actor_user_id=current_user.id)
        return [MemberResponse.from_domain(item, await service.get_user(item.user_id)) for item in memberships]
    except Exception as error:
        _translate_membership_error(error)
        raise


@router.post("/spaces/{space_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def add_member(
    space_id: UUID,
    payload: MemberCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MembershipServicePort, Depends(get_membership_service)],
) -> MemberResponse:
    try:
        membership = await service.add_member(
            space_id=space_id,
            actor_user_id=current_user.id,
            email=payload.email,
            role=payload.role,
        )
        return MemberResponse.from_domain(membership, await service.get_user(membership.user_id))
    except Exception as error:
        _translate_membership_error(error)
        raise


@router.patch("/spaces/{space_id}/members/{member_user_id}", response_model=MemberResponse)
async def change_member_role(
    space_id: UUID,
    member_user_id: UUID,
    payload: MemberRoleRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MembershipServicePort, Depends(get_membership_service)],
) -> MemberResponse:
    try:
        membership = await service.change_role(
            space_id=space_id,
            actor_user_id=current_user.id,
            member_user_id=member_user_id,
            role=payload.role,
        )
        return MemberResponse.from_domain(membership, await service.get_user(membership.user_id))
    except Exception as error:
        _translate_membership_error(error)
        raise


@router.delete("/spaces/{space_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    space_id: UUID,
    member_user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MembershipServicePort, Depends(get_membership_service)],
) -> Response:
    try:
        await service.remove_member(
            space_id=space_id,
            actor_user_id=current_user.id,
            member_user_id=member_user_id,
        )
    except Exception as error:
        _translate_membership_error(error)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)
