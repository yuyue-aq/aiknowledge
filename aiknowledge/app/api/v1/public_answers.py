from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_database_session
from app.core.errors import AppError
from app.domain.public_answers import (
    PublicAnswer,
    PublicAnswerNotFoundError,
    PublicAnswerRuleViolationError,
    PublicAnswerSourceRef,
    PublicAnswerStatus,
)
from app.domain.spaces import SpaceAccessDeniedError, SpaceNotFoundError
from app.domain.users import User


router = APIRouter(tags=['public answers'])


class PublicAnswerServicePort(Protocol):
    async def list(self, space_id: UUID, **kwargs: object) -> list[PublicAnswer]: ...
    async def create(self, **kwargs: object) -> PublicAnswer: ...
    async def update(self, answer_id: UUID, **kwargs: object) -> PublicAnswer: ...
    async def submit_for_review(self, answer_id: UUID, **kwargs: object) -> PublicAnswer: ...
    async def approve(self, answer_id: UUID, **kwargs: object) -> PublicAnswer: ...
    async def publish(self, answer_id: UUID, **kwargs: object) -> PublicAnswer: ...
    async def withdraw(self, answer_id: UUID, **kwargs: object) -> PublicAnswer: ...


def get_public_answer_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope='function')],
) -> PublicAnswerServicePort:
    return request.app.state.public_answer_service_factory(session)


class PublicAnswerSourceRefRequest(BaseModel):
    document_id: UUID
    document_version_id: UUID

    def to_domain(self) -> PublicAnswerSourceRef:
        return PublicAnswerSourceRef(self.document_id, self.document_version_id)


class PublicAnswerCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category_id: UUID
    question: str = Field(min_length=1, max_length=2_000)
    answer: str = Field(min_length=1, max_length=20_000)
    source_refs: list[PublicAnswerSourceRefRequest] = Field(default_factory=list, max_length=100)


class PublicAnswerUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category_id: UUID | None = None
    question: str | None = Field(default=None, min_length=1, max_length=2_000)
    answer: str | None = Field(default=None, min_length=1, max_length=20_000)
    source_refs: list[PublicAnswerSourceRefRequest] | None = Field(default=None, max_length=100)


class PublicAnswerResponse(BaseModel):
    id: UUID
    space_id: UUID
    category_id: UUID
    question: str
    answer: str
    status: PublicAnswerStatus
    source_refs: list[PublicAnswerSourceRefRequest]
    created_at: datetime
    updated_at: datetime
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    published_version_id: UUID | None
    published_version_number: int | None
    withdrawal_reason: str | None

    @classmethod
    def from_domain(cls, answer: PublicAnswer) -> 'PublicAnswerResponse':
        return cls(
            id=answer.id, space_id=answer.space_id, category_id=answer.category_id,
            question=answer.question, answer=answer.answer, status=answer.status,
            source_refs=[PublicAnswerSourceRefRequest(
                document_id=source.document_id, document_version_id=source.document_version_id
            ) for source in answer.source_refs],
            created_at=answer.created_at, updated_at=answer.updated_at,
            reviewed_by=answer.reviewed_by, reviewed_at=answer.reviewed_at,
            published_version_id=answer.published_version_id,
            published_version_number=answer.published_version_number,
            withdrawal_reason=answer.withdrawal_reason,
        )


class PublicAnswerListResponse(BaseModel):
    items: list[PublicAnswerResponse]


class PublicAnswerWithdrawRequest(BaseModel):
    reason: str = Field(default='OWNER_WITHDRAWN', min_length=1, max_length=500)


def _translate_error(error: Exception) -> None:
    if isinstance(error, SpaceAccessDeniedError):
        raise AppError(code='SPACE_ACCESS_DENIED', message=str(error), status_code=403) from error
    if isinstance(error, (SpaceNotFoundError, PublicAnswerNotFoundError)):
        raise AppError(code='PUBLIC_ANSWER_NOT_FOUND', message='公开问答不存在或知识空间不可用。', status_code=404) from error
    if isinstance(error, PublicAnswerRuleViolationError):
        raise AppError(code='PUBLIC_ANSWER_RULE_VIOLATION', message=str(error), status_code=409) from error
    raise error


@router.get('/spaces/{space_id}/public-answers', response_model=PublicAnswerListResponse)
async def list_public_answers(
    space_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: PublicAnswerServicePort = Depends(get_public_answer_service),
) -> PublicAnswerListResponse:
    try:
        answers = await service.list(space_id, actor_user_id=user.id)
    except Exception as error:
        _translate_error(error)
        raise
    return PublicAnswerListResponse(items=[PublicAnswerResponse.from_domain(item) for item in answers])


@router.post('/spaces/{space_id}/public-answers', response_model=PublicAnswerResponse, status_code=status.HTTP_201_CREATED)
async def create_public_answer(
    space_id: UUID,
    payload: PublicAnswerCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: PublicAnswerServicePort = Depends(get_public_answer_service),
) -> PublicAnswerResponse:
    try:
        answer = await service.create(
            space_id=space_id, actor_user_id=user.id, category_id=payload.category_id,
            question=payload.question, answer=payload.answer,
            source_refs=[source.to_domain() for source in payload.source_refs],
        )
    except Exception as error:
        _translate_error(error)
        raise
    return PublicAnswerResponse.from_domain(answer)


@router.patch('/public-answers/{answer_id}', response_model=PublicAnswerResponse)
async def update_public_answer(
    answer_id: UUID,
    payload: PublicAnswerUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: PublicAnswerServicePort = Depends(get_public_answer_service),
) -> PublicAnswerResponse:
    try:
        values = payload.model_dump(exclude_unset=True)
        if 'source_refs' in values and values['source_refs'] is not None:
            values['source_refs'] = [source.to_domain() for source in payload.source_refs or []]
        answer = await service.update(answer_id, actor_user_id=user.id, **values)
    except Exception as error:
        _translate_error(error)
        raise
    return PublicAnswerResponse.from_domain(answer)


@router.post('/public-answers/{answer_id}/submit-for-review', response_model=PublicAnswerResponse)
async def submit_public_answer_for_review(
    answer_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: PublicAnswerServicePort = Depends(get_public_answer_service),
) -> PublicAnswerResponse:
    try:
        answer = await service.submit_for_review(answer_id, actor_user_id=user.id)
    except Exception as error:
        _translate_error(error)
        raise
    return PublicAnswerResponse.from_domain(answer)


@router.post('/public-answers/{answer_id}/approve', response_model=PublicAnswerResponse)
async def approve_public_answer(
    answer_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: PublicAnswerServicePort = Depends(get_public_answer_service),
) -> PublicAnswerResponse:
    try:
        answer = await service.approve(answer_id, actor_user_id=user.id)
    except Exception as error:
        _translate_error(error)
        raise
    return PublicAnswerResponse.from_domain(answer)


@router.post('/public-answers/{answer_id}/publish', response_model=PublicAnswerResponse)
async def publish_public_answer(
    answer_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: PublicAnswerServicePort = Depends(get_public_answer_service),
) -> PublicAnswerResponse:
    try:
        answer = await service.publish(answer_id, actor_user_id=user.id)
    except Exception as error:
        _translate_error(error)
        raise
    return PublicAnswerResponse.from_domain(answer)


@router.post('/public-answers/{answer_id}/withdraw', response_model=PublicAnswerResponse)
async def withdraw_public_answer(
    answer_id: UUID,
    payload: PublicAnswerWithdrawRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: PublicAnswerServicePort = Depends(get_public_answer_service),
) -> PublicAnswerResponse:
    try:
        answer = await service.withdraw(answer_id, actor_user_id=user.id, reason=payload.reason)
    except Exception as error:
        _translate_error(error)
        raise
    return PublicAnswerResponse.from_domain(answer)
