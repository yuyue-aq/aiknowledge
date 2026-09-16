from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session
from app.api.v1.conversations import get_public_scope
from app.core.errors import AppError
from app.domain.conversations import (
    Feedback,
    FeedbackAccessDeniedError,
    FeedbackGuestDisabledError,
    FeedbackMessageNotFoundError,
    FeedbackRating,
    FeedbackReason,
)
from app.domain.spaces import PublicRetrievalScope


router = APIRouter(tags=["feedback"])


class FeedbackServicePort(Protocol):
    async def create_owner_feedback(
        self,
        *,
        message_id: UUID,
        rating: FeedbackRating,
        reason: FeedbackReason | None,
        comment: str | None,
    ) -> Feedback: ...

    async def create_public_feedback(
        self,
        *,
        message_id: UUID,
        scope: PublicRetrievalScope,
        rating: FeedbackRating,
        reason: FeedbackReason | None,
        comment: str | None,
    ) -> Feedback: ...

    async def list_space_feedback(self, space_id: UUID) -> list[Feedback]: ...


def get_feedback_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> FeedbackServicePort:
    return request.app.state.feedback_service_factory(session)


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    rating: FeedbackRating
    reason: FeedbackReason | None = None
    comment: str | None = Field(default=None, max_length=1_000)


class FeedbackResponse(BaseModel):
    id: UUID
    message_id: UUID
    rating: FeedbackRating
    reason: FeedbackReason | None
    comment: str | None
    is_guest: bool
    created_at: datetime

    @classmethod
    def from_domain(cls, feedback: Feedback) -> "FeedbackResponse":
        return cls(
            id=feedback.id,
            message_id=feedback.message_id,
            rating=feedback.rating,
            reason=feedback.reason,
            comment=feedback.comment,
            is_guest=feedback.is_guest,
            created_at=feedback.created_at,
        )


class FeedbackListResponse(BaseModel):
    items: list[FeedbackResponse]


def _translate_feedback_error(error: Exception) -> None:
    if isinstance(error, FeedbackMessageNotFoundError):
        raise AppError(code="MESSAGE_NOT_FOUND", message="回答消息不存在。", status_code=404) from error
    if isinstance(error, FeedbackGuestDisabledError):
        raise AppError(
            code="GUEST_FEEDBACK_DISABLED",
            message="当前公开空间未开启访客反馈。",
            status_code=403,
        ) from error
    if isinstance(error, FeedbackAccessDeniedError):
        raise AppError(code="FEEDBACK_ACCESS_DENIED", message="反馈访问范围不匹配。", status_code=403) from error
    if isinstance(error, ValueError):
        raise AppError(code="FEEDBACK_INVALID", message=str(error), status_code=422) from error
    raise error


@router.post(
    "/messages/{message_id}/feedback",
    status_code=status.HTTP_201_CREATED,
    response_model=FeedbackResponse,
)
async def create_owner_feedback(
    message_id: UUID,
    payload: FeedbackRequest,
    service: FeedbackServicePort = Depends(get_feedback_service),
) -> FeedbackResponse:
    try:
        feedback = await service.create_owner_feedback(
            message_id=message_id, **payload.model_dump()
        )
    except Exception as error:
        _translate_feedback_error(error)
        raise
    return FeedbackResponse.from_domain(feedback)


@router.post(
    "/public/messages/{message_id}/feedback",
    status_code=status.HTTP_201_CREATED,
    response_model=FeedbackResponse,
)
async def create_public_feedback(
    message_id: UUID,
    payload: FeedbackRequest,
    scope: PublicRetrievalScope = Depends(get_public_scope),
    service: FeedbackServicePort = Depends(get_feedback_service),
) -> FeedbackResponse:
    try:
        feedback = await service.create_public_feedback(
            message_id=message_id,
            scope=scope,
            **payload.model_dump(),
        )
    except Exception as error:
        _translate_feedback_error(error)
        raise
    return FeedbackResponse.from_domain(feedback)


@router.get("/spaces/{space_id}/feedback", response_model=FeedbackListResponse)
async def list_space_feedback(
    space_id: UUID,
    service: FeedbackServicePort = Depends(get_feedback_service),
) -> FeedbackListResponse:
    return FeedbackListResponse(
        items=[
            FeedbackResponse.from_domain(item)
            for item in await service.list_space_feedback(space_id)
        ]
    )
