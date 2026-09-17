from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class SpaceVisibility(StrEnum):
    PRIVATE = "PRIVATE"
    PUBLIC = "PUBLIC"


class SpacePlan(StrEnum):
    FREE = "FREE"
    PRO = "PRO"
    TEAM = "TEAM"


class ShareLinkStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class SpaceNotFoundError(LookupError):
    pass


class SpaceAccessDeniedError(PermissionError):
    """The caller belongs to a space but lacks the role for this operation."""

    pass


class CategoryNotFoundError(LookupError):
    pass


class ShareLinkNotFoundError(LookupError):
    pass


class SpaceRuleViolationError(ValueError):
    pass


class PublicAccessDeniedError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class KnowledgeSpace:
    id: UUID
    name: str
    description: str | None
    visibility: SpaceVisibility
    guest_feedback_enabled: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    owner_user_id: UUID | None = None
    plan: SpacePlan = SpacePlan.FREE

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None


@dataclass(frozen=True, slots=True)
class Category:
    id: UUID
    space_id: UUID
    name: str
    description: str | None
    is_open: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    display_name: str | None = None
    display_description: str | None = None
    is_default: bool = False

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None


@dataclass(frozen=True, slots=True)
class ShareLink:
    id: UUID
    space_id: UUID
    category_ids: tuple[UUID, ...]
    token_hash: str
    status: ShareLinkStatus
    created_at: datetime
    revoked_at: datetime | None = None
    expires_at: datetime | None = None
    password_hash: str | None = None
    visitor_question_limit: int | None = None
    # Optional browser Origin allowlist for embeds. Empty means no additional
    # Origin restriction (the normal share token and session checks remain).
    allowed_origins: tuple[str, ...] = ()

    def is_active(self, *, at: datetime) -> bool:
        return (
            self.status == ShareLinkStatus.ACTIVE
            and self.revoked_at is None
            and (self.expires_at is None or self.expires_at > at)
        )


@dataclass(frozen=True, slots=True)
class CreatedShareLink:
    link: ShareLink
    # The raw token is deliberately returned only by the creation result; it
    # has no field on ShareLink and never reaches database persistence.
    token: str


@dataclass(frozen=True, slots=True)
class PublicRetrievalScope:
    share_link_id: UUID
    space_id: UUID
    category_ids: tuple[UUID, ...]
    visitor_id: str | None = None
    visitor_question_limit: int | None = None
    allowed_origins: tuple[str, ...] = ()


class PublicAccessEventType(StrEnum):
    """Anonymized event types used for public-space operational analytics."""

    SESSION = "SESSION"
    CONVERSATION = "CONVERSATION"
    QUESTION = "QUESTION"


@dataclass(frozen=True, slots=True)
class PublicAccessEvent:
    id: UUID
    space_id: UUID
    share_link_id: UUID
    visitor_id: str
    event_type: PublicAccessEventType
    origin: str | None
    user_agent: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PublicAnalyticsDay:
    date: str
    sessions: int
    conversations: int
    questions: int
    unique_visitors: int


@dataclass(frozen=True, slots=True)
class PublicAnalytics:
    space_id: UUID
    period_start: datetime
    period_end: datetime
    sessions: int
    conversations: int
    questions: int
    unique_visitors: int
    daily: tuple[PublicAnalyticsDay, ...]
    # Aggregated model-call telemetry. Values are intentionally coarse and
    # omit question/answer text so operators can observe cost and latency
    # without turning analytics into a content log.
    answer_count: int = 0
    failed_answers: int = 0
    latency_p50_ms: int | None = None
    latency_p95_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class PublicQuestionRecord:
    """A privacy-preserving record of one public visitor question."""

    id: UUID
    share_link_id: UUID
    visitor_id: str
    conversation_id: UUID | None
    question_hash: str
    created_at: datetime
    is_hidden: bool = False
    moderation_note: str | None = None
    moderated_at: datetime | None = None
    space_id: UUID | None = None
