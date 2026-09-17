from __future__ import annotations

import asyncio
import json
from datetime import datetime
from dataclasses import replace
from typing import Annotated, Protocol
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session, get_optional_current_user
from app.core.errors import AppError
from app.domain.conversations import (
    CitationSnapshot,
    Conversation,
    ConversationAccessDeniedError,
    ConversationAnswer,
    ConversationDetail,
    ConversationNotFoundError,
)
from app.domain.rag import AnswerStatus
from app.domain.spaces import (
    Category,
    KnowledgeSpace,
    PublicAccessDeniedError,
    PublicAccessEventType,
    PublicRetrievalScope,
)
from app.domain.users import User
from app.services.conversations import ConversationQuestionError
from app.services.public_access import PublicSessionInvalidError
from app.services.public_questions import (
    PublicQuestionLimitExceededError,
    PublicQuestionLimitService,
)
from app.services.usage import UsageLimitExceededError


router = APIRouter(tags=["conversations"])
PUBLIC_SESSION_COOKIE = "aiknowledge_public_session"


class ConversationServicePort(Protocol):
    async def create_owner_conversation(
        self, *, space_id: UUID, title: str | None = None, owner_user_id: UUID | None = None
    ) -> Conversation: ...

    async def create_public_conversation(
        self, *, scope: PublicRetrievalScope, title: str | None = None
    ) -> Conversation: ...

    async def ask_owner(
        self, *, conversation_id: UUID, question: str, owner_user_id: UUID | None = None
    ) -> ConversationAnswer: ...

    async def ask_public(
        self,
        *,
        conversation_id: UUID,
        scope: PublicRetrievalScope,
        question: str,
    ) -> ConversationAnswer: ...

    async def get_owner_conversation(self, conversation_id: UUID, *, owner_user_id: UUID | None = None) -> ConversationDetail: ...

    async def list_owner_conversations(self, space_id: UUID, *, owner_user_id: UUID | None = None) -> tuple[Conversation, ...]: ...

    async def delete_owner_conversation(self, conversation_id: UUID, *, owner_user_id: UUID | None = None) -> None: ...


class PublicSpaceServicePort(Protocol):
    async def resolve_public_scope(
        self, raw_token: str, password: str | None = None
    ) -> PublicRetrievalScope: ...

    async def resolve_public_scope_by_link_id(
        self, share_link_id: UUID
    ) -> PublicRetrievalScope: ...

    async def get_space(self, space_id: UUID) -> KnowledgeSpace: ...

    async def list_categories(self, space_id: UUID) -> list[Category]: ...


class PublicSessionCodecPort(Protocol):
    def issue(self, share_link_id: UUID) -> str: ...

    def read_link_id(self, token: str) -> UUID: ...

    def read_session(self, token: str) -> tuple[UUID, str]: ...


class PublicQuestionLimitServicePort(Protocol):
    async def check_and_record(
        self, *, scope: PublicRetrievalScope, conversation_id: UUID | None, question: str
    ) -> None: ...


class PublicAnalyticsServicePort(Protocol):
    async def record_event(self, **kwargs: object) -> object: ...


def get_conversation_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> ConversationServicePort:
    return request.app.state.conversation_service_factory(session)


def get_public_space_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> PublicSpaceServicePort:
    return request.app.state.space_service_factory(session)


def get_public_session_codec(request: Request) -> PublicSessionCodecPort:
    return request.app.state.public_session_codec


def get_public_question_limit_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> PublicQuestionLimitServicePort:
    return request.app.state.public_question_limit_service_factory(session)


def get_public_analytics_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> PublicAnalyticsServicePort:
    return request.app.state.public_analytics_service_factory(session)


async def get_public_scope(
    request: Request,
    public_session: Annotated[str | None, Cookie(alias=PUBLIC_SESSION_COOKIE)] = None,
    codec: PublicSessionCodecPort = Depends(get_public_session_codec),
    service: PublicSpaceServicePort = Depends(get_public_space_service),
) -> PublicRetrievalScope:
    if not public_session:
        raise AppError(
            code="PUBLIC_SESSION_REQUIRED",
            message="请先通过有效分享链接进入公开空间。",
            status_code=401,
        )
    try:
        share_link_id, visitor_id = codec.read_session(public_session)
        scope = await service.resolve_public_scope_by_link_id(share_link_id)
        _enforce_public_origin(scope, request.headers.get("origin"))
        return PublicRetrievalScope(
            share_link_id=scope.share_link_id,
            space_id=scope.space_id,
            category_ids=scope.category_ids,
            visitor_id=visitor_id if scope.visitor_question_limit is not None else None,
            visitor_question_limit=scope.visitor_question_limit,
            allowed_origins=scope.allowed_origins,
        )
    except (PublicSessionInvalidError, PublicAccessDeniedError) as error:
        raise AppError(
            code="PUBLIC_ACCESS_DENIED",
            message="公开访问已失效，请重新打开有效分享链接。",
            status_code=403,
        ) from error


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    space_id: UUID
    title: str | None = Field(default=None, max_length=200)


class PublicConversationCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=200)


class ConversationResponse(BaseModel):
    id: UUID
    space_id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, conversation: Conversation) -> "ConversationResponse":
        return cls(
            id=conversation.id,
            space_id=conversation.space_id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class QuestionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=2_000)
    stream: bool = False


class OwnerCitationResponse(BaseModel):
    document_name: str
    quoted_text: str
    page_number: int | None
    ordinal: int
    score: float

    @classmethod
    def from_domain(cls, citation: CitationSnapshot) -> "OwnerCitationResponse":
        return cls(
            document_name=citation.document_name,
            quoted_text=citation.quoted_text,
            page_number=citation.page_number,
            ordinal=citation.ordinal,
            score=citation.score,
        )


class OwnerAnswerResponse(BaseModel):
    message_id: UUID
    status: AnswerStatus
    answer: str
    model: str | None
    citations: list[OwnerCitationResponse]

    @classmethod
    def from_domain(cls, answer: ConversationAnswer) -> "OwnerAnswerResponse":
        assistant = answer.assistant
        assert assistant.answer_status is not None
        return cls(
            message_id=assistant.id,
            status=assistant.answer_status,
            answer=assistant.content,
            model=assistant.model,
            citations=[OwnerCitationResponse.from_domain(item) for item in answer.citations],
        )


class OwnerHistoryMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    status: AnswerStatus | None
    model: str | None
    created_at: datetime
    citations: list[OwnerCitationResponse]


class OwnerConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: list[OwnerHistoryMessageResponse]

    @classmethod
    def from_domain(cls, detail: ConversationDetail) -> "OwnerConversationDetailResponse":
        return cls(
            conversation=ConversationResponse.from_domain(detail.conversation),
            messages=[
                OwnerHistoryMessageResponse(
                    id=message.id,
                    role=message.role.value,
                    content=message.content,
                    status=message.answer_status,
                    model=message.model,
                    created_at=message.created_at,
                    citations=[
                        OwnerCitationResponse.from_domain(citation)
                        for citation in detail.citations_by_message.get(message.id, ())
                    ],
                )
                for message in detail.messages
            ],
        )


class PublicAnswerResponse(BaseModel):
    """Intentionally source-free DTO for anonymous guest access."""

    message_id: UUID
    status: AnswerStatus
    answer: str

    @classmethod
    def from_domain(cls, answer: ConversationAnswer) -> "PublicAnswerResponse":
        assistant = answer.assistant
        assert assistant.answer_status is not None
        return cls(
            message_id=assistant.id,
            status=assistant.answer_status,
            answer=assistant.content,
        )


class PublicSessionRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    password: str | None = Field(default=None, min_length=4, max_length=128)


class PublicQueryRequest(BaseModel):
    """Token-based query contract for embeds and server-to-server clients."""

    token: str = Field(min_length=1, max_length=512)
    password: str | None = Field(default=None, min_length=4, max_length=128)
    question: str = Field(min_length=1, max_length=2_000)


class PublicCategoryResponse(BaseModel):
    name: str
    description: str | None


class PublicSpaceResponse(BaseModel):
    name: str
    description: str | None
    categories: list[PublicCategoryResponse]


def _public_space_response(
    space: KnowledgeSpace, categories: list[Category], scope: PublicRetrievalScope
) -> PublicSpaceResponse:
    allowed = set(scope.category_ids)
    return PublicSpaceResponse(
        name=space.name,
        description=space.description,
        categories=[
            PublicCategoryResponse(
                name=category.display_name or category.name,
                description=category.display_description or category.description,
            )
            for category in categories
            if category.id in allowed and category.is_open and category.is_active
        ],
    )


def _enforce_public_origin(scope: PublicRetrievalScope, origin: str | None) -> None:
    """Enforce a share-link Origin allowlist when the browser supplies Origin."""

    if not scope.allowed_origins or not origin:
        return
    value = origin.strip().rstrip("/")
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        raise PublicAccessDeniedError("当前来源不在分享链接允许范围内。")
    try:
        port = parsed.port
    except ValueError as error:
        raise PublicAccessDeniedError("当前来源不在分享链接允许范围内。") from error
    normalized = f"{parsed.scheme.lower()}://{parsed.hostname.lower()}"
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    if port is not None and not default_port:
        normalized += f":{port}"
    if normalized not in scope.allowed_origins:
        raise PublicAccessDeniedError("当前来源不在分享链接允许范围内。")


def _translate_conversation_error(error: Exception) -> None:
    if isinstance(error, UsageLimitExceededError):
        raise AppError(code="USAGE_LIMIT_EXCEEDED", message=str(error), status_code=429) from error
    if isinstance(error, ConversationNotFoundError):
        raise AppError(code="CONVERSATION_NOT_FOUND", message="对话不存在。", status_code=404) from error
    if isinstance(error, ConversationAccessDeniedError):
        raise AppError(code="CONVERSATION_ACCESS_DENIED", message="对话访问范围不匹配。", status_code=403) from error
    if isinstance(error, ConversationQuestionError):
        raise AppError(code="QUESTION_INVALID", message=str(error), status_code=422) from error
    if isinstance(error, PublicAccessDeniedError):
        raise AppError(
            code="PUBLIC_ACCESS_DENIED",
            message="公开访问已失效，请重新打开有效分享链接。",
            status_code=403,
        ) from error
    if isinstance(error, PublicQuestionLimitExceededError):
        raise AppError(
            code="PUBLIC_QUESTION_LIMIT_REACHED",
            message="该分享链接的访客提问次数已用完。",
            status_code=429,
        ) from error
    raise error


_SSE_CHUNK_SIZE = 24


def _chunk_text(text: str, *, chunk_size: int = _SSE_CHUNK_SIZE) -> tuple[str, ...]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return tuple(text[index : index + chunk_size] for index in range(0, len(text), chunk_size))


def _as_sse(payload: BaseModel, request: Request) -> StreamingResponse:
    async def events():
        answer = getattr(payload, "answer", "")
        for chunk in _chunk_text(answer):
            if await request.is_disconnected():
                return
            yield f"event: delta\ndata: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)
        if await request.is_disconnected():
            return
        yield f"event: answer\ndata: {json.dumps(payload.model_dump(mode='json'), ensure_ascii=False)}\n\n"
        await asyncio.sleep(0)
        if await request.is_disconnected():
            return
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/owner/conversations",
    status_code=status.HTTP_201_CREATED,
    response_model=ConversationResponse,
)
async def create_owner_conversation(
    payload: ConversationCreateRequest,
    service: ConversationServicePort = Depends(get_conversation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> ConversationResponse:
    try:
        kwargs = payload.model_dump()
        if _current_user is not None:
            kwargs["owner_user_id"] = _current_user.id
        conversation = await service.create_owner_conversation(**kwargs)
    except Exception as error:
        _translate_conversation_error(error)
        raise
    return ConversationResponse.from_domain(conversation)


@router.get(
    "/owner/conversations",
    response_model=list[ConversationResponse],
)
async def list_owner_conversations(
    space_id: UUID,
    service: ConversationServicePort = Depends(get_conversation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> list[ConversationResponse]:
    try:
        if _current_user is None:
            conversations = await service.list_owner_conversations(space_id)
        else:
            conversations = await service.list_owner_conversations(
                space_id, owner_user_id=_current_user.id
            )
    except Exception as error:
        _translate_conversation_error(error)
        raise
    return [ConversationResponse.from_domain(item) for item in conversations]


@router.post(
    "/owner/conversations/{conversation_id}/messages",
    response_model=OwnerAnswerResponse,
)
async def ask_owner(
    conversation_id: UUID,
    payload: QuestionRequest,
    request: Request,
    service: ConversationServicePort = Depends(get_conversation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> OwnerAnswerResponse | StreamingResponse:
    try:
        kwargs: dict[str, object] = {
            "conversation_id": conversation_id,
            "question": payload.question,
        }
        if _current_user is not None:
            kwargs["owner_user_id"] = _current_user.id
        result = await service.ask_owner(**kwargs)
    except Exception as error:
        _translate_conversation_error(error)
        raise
    response = OwnerAnswerResponse.from_domain(result)
    return _as_sse(response, request) if payload.stream else response


@router.get(
    "/owner/conversations/{conversation_id}",
    response_model=OwnerConversationDetailResponse,
)
async def get_owner_conversation(
    conversation_id: UUID,
    service: ConversationServicePort = Depends(get_conversation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> OwnerConversationDetailResponse:
    try:
        if _current_user is None:
            detail = await service.get_owner_conversation(conversation_id)
        else:
            detail = await service.get_owner_conversation(
                conversation_id, owner_user_id=_current_user.id
            )
    except Exception as error:
        _translate_conversation_error(error)
        raise
    return OwnerConversationDetailResponse.from_domain(detail)


@router.delete("/owner/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_owner_conversation(
    conversation_id: UUID,
    service: ConversationServicePort = Depends(get_conversation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> Response:
    try:
        if _current_user is None:
            await service.delete_owner_conversation(conversation_id)
        else:
            await service.delete_owner_conversation(
                conversation_id, owner_user_id=_current_user.id
            )
    except Exception as error:
        _translate_conversation_error(error)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/public/session",
    response_model=PublicSpaceResponse,
)
async def create_public_session(
    payload: PublicSessionRequest,
    response: Response,
    request: Request,
    service: PublicSpaceServicePort = Depends(get_public_space_service),
    codec: PublicSessionCodecPort = Depends(get_public_session_codec),
    analytics: PublicAnalyticsServicePort = Depends(get_public_analytics_service),
) -> PublicSpaceResponse:
    try:
        if payload.password is None:
            scope = await service.resolve_public_scope(payload.token)
        else:
            scope = await service.resolve_public_scope(payload.token, payload.password)
        _enforce_public_origin(scope, request.headers.get("origin"))
        space = await service.get_space(scope.space_id)
        categories = await service.list_categories(scope.space_id)
    except Exception as error:
        _translate_conversation_error(error)
        raise
    session_token = codec.issue(scope.share_link_id)
    try:
        _, visitor_id = codec.read_session(session_token)
        await analytics.record_event(
            space_id=scope.space_id,
            share_link_id=scope.share_link_id,
            visitor_id=visitor_id,
            event_type=PublicAccessEventType.SESSION,
            origin=request.headers.get("origin"),
            user_agent=request.headers.get("user-agent"),
        )
    except Exception:
        # Analytics is deliberately best-effort; link validation and the
        # public session must remain available when telemetry is degraded.
        pass
    response.set_cookie(
        key=PUBLIC_SESSION_COOKIE,
        value=session_token,
        max_age=request.app.state.settings.public_session_ttl_seconds,
        httponly=True,
        secure=request.app.state.settings.public_session_cookie_secure,
        samesite="lax",
        path="/api/v1/public",
    )
    return _public_space_response(space, categories, scope)


@router.get("/public/space", response_model=PublicSpaceResponse)
async def get_public_space(
    scope: PublicRetrievalScope = Depends(get_public_scope),
    service: PublicSpaceServicePort = Depends(get_public_space_service),
) -> PublicSpaceResponse:
    try:
        space = await service.get_space(scope.space_id)
        categories = await service.list_categories(scope.space_id)
    except Exception as error:
        _translate_conversation_error(error)
        raise
    return _public_space_response(space, categories, scope)


@router.post("/public/query", response_model=PublicAnswerResponse)
async def public_query(
    payload: PublicQueryRequest,
    request: Request,
    service: ConversationServicePort = Depends(get_conversation_service),
    space_service: PublicSpaceServicePort = Depends(get_public_space_service),
    codec: PublicSessionCodecPort = Depends(get_public_session_codec),
    question_limit_service: PublicQuestionLimitServicePort = Depends(get_public_question_limit_service),
) -> PublicAnswerResponse:
    """Answer one share-link question without requiring a browser cookie.

    The raw share token is accepted only in this request body, immediately
    resolved against the live link and never persisted or returned.  The
    resulting response deliberately uses the same source-free DTO as the
    cookie-based public conversation endpoint.
    """

    try:
        if payload.password is None:
            raw_scope = await space_service.resolve_public_scope(payload.token)
        else:
            raw_scope = await space_service.resolve_public_scope(payload.token, payload.password)
        _enforce_public_origin(raw_scope, request.headers.get("origin"))
        session_token = codec.issue(raw_scope.share_link_id)
        _, visitor_id = codec.read_session(session_token)
        scope = replace(
            raw_scope,
            visitor_id=visitor_id if raw_scope.visitor_question_limit is not None else None,
        )
        # Check and record before creating a conversation so a rejected query
        # cannot leave an orphaned public conversation row.
        await question_limit_service.check_and_record(
            scope=scope, conversation_id=None, question=payload.question
        )
        conversation = await service.create_public_conversation(scope=scope)
        result = await service.ask_public(
            conversation_id=conversation.id,
            scope=scope,
            question=payload.question,
        )
    except Exception as error:
        _translate_conversation_error(error)
        raise
    return PublicAnswerResponse.from_domain(result)


@router.post(
    "/public/conversations",
    status_code=status.HTTP_201_CREATED,
    response_model=ConversationResponse,
)
async def create_public_conversation(
    payload: PublicConversationCreateRequest,
    scope: PublicRetrievalScope = Depends(get_public_scope),
    service: ConversationServicePort = Depends(get_conversation_service),
    analytics: PublicAnalyticsServicePort = Depends(get_public_analytics_service),
) -> ConversationResponse:
    try:
        conversation = await service.create_public_conversation(
            scope=scope, title=payload.title
        )
        try:
            await analytics.record_event(
                space_id=scope.space_id,
                share_link_id=scope.share_link_id,
                visitor_id=scope.visitor_id or "anonymous",
                event_type=PublicAccessEventType.CONVERSATION,
            )
        except Exception:
            pass
    except Exception as error:
        _translate_conversation_error(error)
        raise
    return ConversationResponse.from_domain(conversation)


@router.post(
    "/public/conversations/{conversation_id}/messages",
    response_model=PublicAnswerResponse,
)
async def ask_public(
    conversation_id: UUID,
    payload: QuestionRequest,
    request: Request,
    scope: PublicRetrievalScope = Depends(get_public_scope),
    service: ConversationServicePort = Depends(get_conversation_service),
    question_limit_service: PublicQuestionLimitServicePort = Depends(get_public_question_limit_service),
) -> PublicAnswerResponse | StreamingResponse:
    try:
        await question_limit_service.check_and_record(
            scope=scope,
            conversation_id=conversation_id,
            question=payload.question,
        )
        result = await service.ask_public(
            conversation_id=conversation_id,
            scope=scope,
            question=payload.question,
        )
    except Exception as error:
        _translate_conversation_error(error)
        raise
    response = PublicAnswerResponse.from_domain(result)
    return _as_sse(response, request) if payload.stream else response
