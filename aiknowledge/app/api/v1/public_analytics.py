from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session, get_optional_current_user
from app.core.errors import AppError
from app.domain.spaces import (
    PublicAccessEvent,
    PublicAnalytics,
    PublicAnalyticsDay,
    PublicQuestionRecord,
)
from app.domain.users import User
from app.services.public_analytics import (
    PublicAnalyticsAccessDeniedError,
    PublicQuestionModerationError,
)


router = APIRouter(tags=["public-analytics"])


class PublicAnalyticsServicePort(Protocol):
    async def record_event(self, **kwargs: object) -> PublicAccessEvent: ...

    async def get_analytics(self, space_id: UUID, **kwargs: object) -> PublicAnalytics: ...

    async def moderate_question(self, question_id: UUID, **kwargs: object) -> PublicQuestionRecord: ...


def get_public_analytics_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> PublicAnalyticsServicePort:
    return request.app.state.public_analytics_service_factory(session)


class PublicAnalyticsDayResponse(BaseModel):
    date: str
    sessions: int
    conversations: int
    questions: int
    unique_visitors: int

    @classmethod
    def from_domain(cls, value: PublicAnalyticsDay) -> "PublicAnalyticsDayResponse":
        return cls(
            date=value.date,
            sessions=value.sessions,
            conversations=value.conversations,
            questions=value.questions,
            unique_visitors=value.unique_visitors,
        )


class PublicAnalyticsResponse(BaseModel):
    space_id: UUID
    period_start: datetime
    period_end: datetime
    sessions: int
    conversations: int
    questions: int
    unique_visitors: int
    daily: list[PublicAnalyticsDayResponse]
    answer_count: int
    failed_answers: int
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    input_tokens: int
    output_tokens: int
    estimated_cost: float

    @classmethod
    def from_domain(cls, value: PublicAnalytics) -> "PublicAnalyticsResponse":
        return cls(
            space_id=value.space_id,
            period_start=value.period_start,
            period_end=value.period_end,
            sessions=value.sessions,
            conversations=value.conversations,
            questions=value.questions,
            unique_visitors=value.unique_visitors,
            daily=[PublicAnalyticsDayResponse.from_domain(item) for item in value.daily],
            answer_count=value.answer_count,
            failed_answers=value.failed_answers,
            latency_p50_ms=value.latency_p50_ms,
            latency_p95_ms=value.latency_p95_ms,
            input_tokens=value.input_tokens,
            output_tokens=value.output_tokens,
            estimated_cost=value.estimated_cost,
        )


class PublicQuestionModerationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    is_hidden: bool
    moderation_note: str | None = Field(default=None, max_length=1_000)


class PublicQuestionModerationResponse(BaseModel):
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
    def from_domain(cls, value: PublicQuestionRecord) -> "PublicQuestionModerationResponse":
        return cls(
            id=value.id,
            share_link_id=value.share_link_id,
            visitor_id=value.visitor_id,
            conversation_id=value.conversation_id,
            question_hash=value.question_hash,
            created_at=value.created_at,
            is_hidden=value.is_hidden,
            moderation_note=value.moderation_note,
            moderated_at=value.moderated_at,
        )


def _translate(error: Exception) -> None:
    if isinstance(error, PublicAnalyticsAccessDeniedError):
        raise AppError(
            code="PUBLIC_ANALYTICS_ACCESS_DENIED",
            message=str(error),
            status_code=403,
        ) from error
    if isinstance(error, PublicQuestionModerationError):
        raise AppError(
            code="PUBLIC_QUESTION_NOT_FOUND",
            message=str(error),
            status_code=404,
        ) from error
    if isinstance(error, ValueError):
        raise AppError(code="PUBLIC_ANALYTICS_INVALID", message=str(error), status_code=422) from error
    raise error


@router.get("/spaces/{space_id}/public-analytics", response_model=PublicAnalyticsResponse)
async def get_public_analytics(
    space_id: UUID,
    days: int = 30,
    service: PublicAnalyticsServicePort = Depends(get_public_analytics_service),
    current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> PublicAnalyticsResponse:
    try:
        analytics = await service.get_analytics(
            space_id,
            days=days,
            **({"owner_user_id": current_user.id} if current_user is not None else {}),
        )
    except Exception as error:
        _translate(error)
        raise
    return PublicAnalyticsResponse.from_domain(analytics)


@router.patch(
    "/public-questions/{question_id}", response_model=PublicQuestionModerationResponse
)
async def moderate_public_question(
    question_id: UUID,
    payload: PublicQuestionModerationRequest,
    service: PublicAnalyticsServicePort = Depends(get_public_analytics_service),
    current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> PublicQuestionModerationResponse:
    try:
        record = await service.moderate_question(
            question_id,
            is_hidden=payload.is_hidden,
            moderation_note=payload.moderation_note,
            **({"owner_user_id": current_user.id} if current_user is not None else {}),
        )
    except Exception as error:
        _translate(error)
        raise
    return PublicQuestionModerationResponse.from_domain(record)
