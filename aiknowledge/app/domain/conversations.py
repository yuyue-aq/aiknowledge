from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.rag import AnswerStatus
from app.domain.evaluation import EvidenceRef


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


class FeedbackReviewStatus(StrEnum):
    PENDING = "PENDING"
    FIXED = "FIXED"
    DEFERRED = "DEFERRED"


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
    source_available: bool = True
    public_answer_version_id: UUID | None = None


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
    document_version_id: UUID | None = None
    source_block_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    content_hash: str | None = None
    token_count: int | None = None
    heading_path: tuple[str, ...] = ()
    context_priority: int | None = None
    score_kind: str = 'cosine'
    dense_rank: int | None = None
    bm25_rank: int | None = None
    fusion_rank: int | None = None
    dense_score: float | None = None
    bm25_score: float | None = None
    fusion_score: float | None = None
    rerank_rank: int | None = None
    rerank_score: float | None = None
    source_type: str = 'DOCUMENT'
    public_answer_version_id: UUID | None = None
    public_answer_title: str | None = None
    public_answer_text: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationAnswer:
    user: ConversationMessage
    assistant: ConversationMessage
    citations: tuple[CitationSnapshot, ...]
    scope_snapshot: tuple[int, int] | None = None
    query_diagnostics: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ConversationDetail:
    conversation: Conversation
    messages: tuple[ConversationMessage, ...]
    citations_by_message: dict[UUID, tuple[CitationSnapshot, ...]]
    query_diagnostics_by_message: dict[UUID, dict[str, object]] = field(default_factory=dict)


class FeedbackMessageNotFoundError(LookupError):
    pass


class FeedbackAccessDeniedError(PermissionError):
    pass


class FeedbackGuestDisabledError(PermissionError):
    pass


class FeedbackNotFoundError(LookupError):
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
    review_status: FeedbackReviewStatus = FeedbackReviewStatus.PENDING
    corrected_answer: str | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None
    data_usage_scope: str = "INTERNAL_ONLY"
    pii_status: str = "UNKNOWN"
    question: str | None = None
    original_answer: str | None = None
    eval_case_id: UUID | None = None
    source_category_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class FeedbackRegressionSource:
    feedback_id: UUID
    space_id: UUID
    question: str
    corrected_answer: str | None
    is_guest: bool
    review_status: FeedbackReviewStatus
    category_ids: tuple[UUID, ...] = ()
    linked_eval_case_id: UUID | None = None


class EvalCaseNotFoundError(LookupError):
    pass


class EvalCaseInUseError(ValueError):
    """Raised when deleting a live case would destroy historical results."""


class EvalFeedbackAlreadyLinkedError(RuntimeError):
    """Raised when a feedback item already has a regression case."""


class EvalAccessDeniedError(PermissionError):
    pass


class EvalRunNotFoundError(LookupError):
    pass


class EvalResultNotFoundError(LookupError):
    pass


class EvalVersionNotFoundError(LookupError):
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
    answerable: bool | None = None
    expected_behavior: str | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    source_feedback_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class EvalSetVersion:
    """Immutable snapshot of an evaluation set for reproducible comparisons."""

    id: UUID
    space_id: UUID
    version_number: int
    label: str
    cases: tuple[EvalCase, ...]
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
    progress_total: int = 0
    progress_completed: int = 0
    heartbeat_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    task_id: str | None = None
    failure_code: str | None = None


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
    execution_snapshot: dict[str, object] | None = None
    retrieval_metrics: dict[str, object] | None = None
    failure_code: str | None = None
    model_grade_suggestions: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationRunDetail:
    run: EvalRun
    results: tuple[EvalResult, ...]
    cases_by_id: dict[UUID, EvalCase]


@dataclass(frozen=True, slots=True)
class EvaluationRunComparison:
    """Two run snapshots selected for quality and regression comparison."""

    baseline: EvaluationRunDetail
    candidate: EvaluationRunDetail

    @staticmethod
    def _case_key(case: EvalCase):
        return (case.question, case.expected_answer, case.scope, tuple(sorted(case.category_ids)),
            tuple(sorted(case.expected_document_ids)), case.answerable, case.expected_behavior, case.evidence_refs)

    @property
    def same_test_set(self) -> bool:
        left, right = self.baseline.cases_by_id, self.candidate.cases_by_id
        return bool(left) and left.keys() == right.keys() and all(self._case_key(case) == self._case_key(right[key]) for key, case in left.items())

    @property
    def question_changes(self) -> list[dict[str, object]]:
        left = {item.eval_case_id: item for item in self.baseline.results}
        right = {item.eval_case_id: item for item in self.candidate.results}
        result = []
        for key in sorted(self.baseline.cases_by_id.keys() | self.candidate.cases_by_id.keys(), key=str):
            before, after = self.baseline.cases_by_id.get(key), self.candidate.cases_by_id.get(key)
            old_result, new_result = left.get(key), right.get(key)
            result.append({'eval_case_id': str(key), 'baseline_question': before.question if before else None,
                'candidate_question': after.question if after else None,
                'comparable': bool(before and after and self._case_key(before) == self._case_key(after)),
                'baseline_status': old_result.answer_status.value if old_result else None,
                'candidate_status': new_result.answer_status.value if new_result else None,
                'baseline_score': old_result.reviewer_score if old_result else None,
                'candidate_score': new_result.reviewer_score if new_result else None})
        return result
