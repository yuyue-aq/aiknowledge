from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class SpaceRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    EDITOR = "EDITOR"
    MEMBER = "MEMBER"


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    email: str
    display_name: str
    password_hash: str
    status: UserStatus
    created_at: datetime
    updated_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class RefreshToken:
    id: UUID
    user_id: UUID
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        from datetime import UTC

        now = datetime.now(UTC)
        expiry = self.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return self.revoked_at is None and expiry > now


@dataclass(frozen=True, slots=True)
class SpaceMembership:
    space_id: UUID
    user_id: UUID
    role: SpaceRole
    created_at: datetime


class AuthDomainError(Exception):
    """Base class for errors that are safe to translate at the API boundary."""


class DuplicateEmailError(AuthDomainError):
    pass


class InvalidCredentialsError(AuthDomainError):
    pass


class InvalidRefreshTokenError(AuthDomainError):
    pass


class UserDisabledError(AuthDomainError):
    pass


class UserNotFoundError(AuthDomainError):
    pass
