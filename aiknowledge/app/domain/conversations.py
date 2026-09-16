from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.rag import AnswerStatus


class ConversationKind(StrEnum):
    OWNER = "OWNER"
    PUBLIC = "PUBLIC"


class MessageRole(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class FeedbackRating(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    NEEDS_CORRECTION = "NEEDS_CORRECTION"


class FeedbackReason(StrEnum):
    OFF_TOPIC = "OFF_TOPIC"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"
    OUTDATED = "OUTDATED"
    INCOMPLETE = "INCOMPLETE"
    MISSING_MATERIAL = "MISSING_MATERIAL"


class EvalRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EvalScope(StrEnum):
    OWNER = "OWNER"
    PUBLIC = "PUBLIC"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class ConversationNotFoundError(LookupError):
    """Raised when a conversation is absent or its owning space is unavailable."""


class ConversationAccessDeniedError(PermissionError):
    """Raised when a public conversation is used outside its share-link scope."""


@dataclass(frozen=True, slots=True)
class Conversation:
    id: UUID
    space_id: UUID
    kind: ConversationKind
    share_link_id: UUID | None
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    created_at: datetime
    answer_status: AnswerStatus | None = None
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class CitationSnapshot:
    id: UUID
    message_id: UUID
    chunk_id: UUID | None
    document_name: str
    quoted_text: str
    page_number: int | None
    ordinal: int
    score: float


@dataclass(frozen=True, slots=True)
class RagRun:
    """Immutable audit snapshot for one persisted conversation answer."""

    id: UUID
    trace_id: UUID
    message_id: UUID
    prompt_version: str
    rewritten_question: str
    model_snapshot: dict[str, object]
    retrieval_config_snapshot: dict[str, object]
    retrieved_chunk_ids: tuple[UUID, ...]
    selected_chunk_ids: tuple[UUID, ...]
    input_tokens: int | None
    output_tokens: int | None
    first_token_latency_ms: int | None
    total_latency_ms: int
    estimated_cost: float | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A server-authorized vector-search hit with source metadata for owners."""

    id: UUID
    document_id: UUID
    document_name: str
    content: str
    page_number: int | None
    ordinal: int
    score: float


@dataclass(frozen=True, slots=True)
class ConversationAnswer:
    user: ConversationMessage
    assistant: ConversationMessage
    citations: tuple[CitationSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ConversationDetail:
    conversation: Conversation
    messages: tuple[ConversationMessage, ...]
    citations_by_message: dict[UUID, tuple[CitationSnapshot, ...]]


class FeedbackMessageNotFoundError(LookupError):
    pass


class FeedbackAccessDeniedError(PermissionError):
    pass


class FeedbackGuestDisabledError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class MessageFeedbackContext:
    message_id: UUID
    space_id: UUID
    conversation_kind: ConversationKind
    share_link_id: UUID | None
    guest_feedback_enabled: bool


@dataclass(frozen=True, slots=True)
class Feedback:
    id: UUID
    message_id: UUID
    space_id: UUID
    rating: FeedbackRating
    reason: FeedbackReason | None
    comment: str | None
    is_guest: bool
    created_at: datetime


class EvalCaseNotFoundError(LookupError):
    pass


class EvalRunNotFoundError(LookupError):
    pass


class EvalResultNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class EvalCase:
    id: UUID
    space_id: UUID
    question: str
    expected_answer: str | None
    expected_document_ids: tuple[UUID, ...]
    scope: EvalScope
    category_ids: tuple[UUID, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EvalRun:
    id: UUID
    space_id: UUID
    status: EvalRunStatus
    retrieval_config_snapshot: dict[str, object]
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_message: str | None = None


@dataclass(frozen=True, slots=True)
class EvalResult:
    id: UUID
    eval_run_id: UUID
    eval_case_id: UUID
    answer_status: AnswerStatus
    answer: str
    citation_count: int
    reviewer_score: float | None = None
    reviewer_note: str | None = None


@dataclass(frozen=True, slots=True)
class EvaluationRunDetail:
    run: EvalRun
    results: tuple[EvalResult, ...]
    cases_by_id: dict[UUID, EvalCase]
