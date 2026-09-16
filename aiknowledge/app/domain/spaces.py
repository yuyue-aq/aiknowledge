from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class SpaceVisibility(StrEnum):
    PRIVATE = "PRIVATE"
    PUBLIC = "PUBLIC"


class ShareLinkStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class SpaceNotFoundError(LookupError):
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
