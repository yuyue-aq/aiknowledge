from __future__ import annotations

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session, get_optional_current_user
from app.core.errors import AppError
from app.domain.spaces import SpacePlan
from app.domain.usage import SpaceUsage
from app.domain.users import User
from app.services.usage import UsageService, UsageSpaceNotFoundError


router = APIRouter(tags=["usage"])


class UsageServicePort(Protocol):
    async def get_usage(self, space_id: UUID, *, owner_user_id: UUID | None = None) -> SpaceUsage: ...


def get_usage_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> UsageServicePort:
    return request.app.state.usage_service_factory(session)


class UsageLimitsResponse(BaseModel):
    documents: int
    members: int
    questions_per_day: int


class UsageResponse(BaseModel):
    space_id: UUID
    plan: SpacePlan
    documents_used: int
    documents_remaining: int
    members_used: int
    members_remaining: int
    questions_used_today: int
    questions_remaining_today: int
    limits: UsageLimitsResponse

    @classmethod
    def from_domain(cls, usage: SpaceUsage) -> "UsageResponse":
        return cls(
            space_id=usage.space_id,
            plan=usage.plan,
            documents_used=usage.documents_used,
            documents_remaining=usage.documents_remaining,
            members_used=usage.members_used,
            members_remaining=usage.members_remaining,
            questions_used_today=usage.questions_used_today,
            questions_remaining_today=usage.questions_remaining_today,
            limits=UsageLimitsResponse(
                documents=usage.limits.documents,
                members=usage.limits.members,
                questions_per_day=usage.limits.questions_per_day,
            ),
        )


@router.get("/spaces/{space_id}/usage", response_model=UsageResponse)
async def get_usage(
    space_id: UUID,
    service: Annotated[UsageServicePort, Depends(get_usage_service)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> UsageResponse:
    try:
        usage = await service.get_usage(
            space_id,
            **({"owner_user_id": current_user.id} if current_user is not None else {}),
        )
    except UsageSpaceNotFoundError as error:
        raise AppError(code="SPACE_NOT_FOUND", message="知识空间不存在。", status_code=404) from error
    return UsageResponse.from_domain(usage)
