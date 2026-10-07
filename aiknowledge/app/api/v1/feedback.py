from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session, get_optional_current_user
from app.api.v1.conversations import get_public_scope
from app.core.errors import AppError
from app.domain.conversations import (
    Feedback,
    FeedbackAccessDeniedError,
    FeedbackGuestDisabledError,
    FeedbackMessageNotFoundError,
    FeedbackRating,
    FeedbackReason,
    FeedbackNotFoundError,
    FeedbackReviewStatus,
)
from app.domain.spaces import PublicRetrievalScope
from app.domain.users import User


router = APIRouter(tags=["feedback"])


class FeedbackServicePort(Protocol):
    async def create_owner_feedback(
        self,
        *,
        message_id: UUID,
        rating: FeedbackRating,
        reason: FeedbackReason | None,
        comment: str | None,
        owner_user_id: UUID | None = None,
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

    async def list_space_feedback(
        self,
        space_id: UUID,
        *,
        review_status: FeedbackReviewStatus | None = None,
        rating: FeedbackRating | None = None,
        is_guest: bool | None = None,
        owner_user_id: UUID | None = None,
    ) -> list[Feedback]: ...

    async def review_feedback(self, **kwargs: object) -> Feedback: ...


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
    question: str | None = None
    original_answer: str | None = None
    id: UUID
    message_id: UUID
    rating: FeedbackRating
    reason: FeedbackReason | None
    comment: str | None
    is_guest: bool
    created_at: datetime
    review_status: FeedbackReviewStatus
    corrected_answer: str | None
    review_note: str | None
    reviewed_at: datetime | None
    data_usage_scope: str
    pii_status: str

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
            review_status=feedback.review_status,
            corrected_answer=feedback.corrected_answer,
            review_note=feedback.review_note,
            reviewed_at=feedback.reviewed_at,
            data_usage_scope=feedback.data_usage_scope,
            pii_status=feedback.pii_status,
            question=feedback.question,
            original_answer=feedback.original_answer,
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
    if isinstance(error, FeedbackNotFoundError):
        raise AppError(code="FEEDBACK_NOT_FOUND", message="反馈记录不存在。", status_code=404) from error
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
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> FeedbackResponse:
    try:
        kwargs = {"message_id": message_id, **payload.model_dump()}
        if _current_user is not None:
            kwargs["owner_user_id"] = _current_user.id
        feedback = await service.create_owner_feedback(**kwargs)
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
    review_status: FeedbackReviewStatus | None = Query(default=None),
    rating: FeedbackRating | None = Query(default=None),
    is_guest: bool | None = Query(default=None),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> FeedbackListResponse:
    if review_status is None and rating is None and is_guest is None and _current_user is None:
        # Keep the endpoint compatible with lightweight service adapters used
        # by integrations that implement the original one-argument contract.
        items = await service.list_space_feedback(space_id)
    else:
        kwargs = {
            "review_status": review_status,
            "rating": rating,
            "is_guest": is_guest,
        }
        if _current_user is not None:
            kwargs["owner_user_id"] = _current_user.id
        items = await service.list_space_feedback(space_id, **kwargs)
    return FeedbackListResponse(
        items=[
            FeedbackResponse.from_domain(item)
            for item in items
        ]
    )


class FeedbackReviewRequest(BaseModel):
    review_status: FeedbackReviewStatus
    corrected_answer: str | None = Field(default=None, max_length=4_000)
    review_note: str | None = Field(default=None, max_length=1_000)
    data_usage_scope: str = Field(default="INTERNAL_ONLY", min_length=1, max_length=32)
    pii_status: str = Field(default="UNKNOWN", min_length=1, max_length=32)


@router.patch("/feedback/{feedback_id}", response_model=FeedbackResponse)
async def review_feedback(
    feedback_id: UUID,
    payload: FeedbackReviewRequest,
    service: FeedbackServicePort = Depends(get_feedback_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> FeedbackResponse:
    try:
        feedback = await service.review_feedback(
            feedback_id=feedback_id,
            **payload.model_dump(),
            **({"owner_user_id": _current_user.id} if _current_user is not None else {}),
        )
    except Exception as error:
        _translate_feedback_error(error)
        raise
    return FeedbackResponse.from_domain(feedback)
