from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Protocol
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.domain.users import (
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    RefreshToken,
    User,
    UserDisabledError,
    UserNotFoundError,
    UserStatus,
)


class AuthRepository(Protocol):
    async def get_user_by_email(self, email: str) -> User | None: ...

    async def get_user(self, user_id: UUID) -> User | None: ...

    async def add_user(self, user: User) -> None: ...

    async def add_refresh_token(self, token: RefreshToken) -> None: ...

    async def get_refresh_token(self, token_hash: str) -> RefreshToken | None: ...

    async def revoke_refresh_token(self, token_id: UUID, revoked_at: datetime) -> None: ...


class AccessTokenError(ValueError):
    """Raised when a signed access token cannot be trusted."""


class AccessTokenCodec:
    """Small dependency-free signed access token codec.

    The token is intentionally opaque to clients and contains only a user id,
    issued-at and expiry. HMAC signing keeps the API stateless while refresh
    tokens remain revocable in the database.
    """

    def __init__(
        self,
        *,
        secret: str,
        ttl_seconds: int = 900,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not secret:
            raise ValueError("access token secret must not be empty")
        if ttl_seconds < 60:
            raise ValueError("access token ttl must be at least 60 seconds")
        self._secret = secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds
        self._clock = clock

    def issue(self, user_id: UUID) -> str:
        now = self._utc_now()
        payload = {
            "sub": str(user_id),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self._ttl_seconds)).timestamp()),
            "typ": "access",
        }
        encoded = self._encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        return f"{encoded}.{self._signature(encoded)}"

    def verify(self, token: str) -> UUID:
        try:
            encoded, signature = token.split(".", 1)
            if not hmac.compare_digest(signature, self._signature(encoded)):
                raise AccessTokenError("invalid signature")
            payload = json.loads(self._decode(encoded))
            if payload.get("typ") != "access":
                raise AccessTokenError("invalid token type")
            if int(payload["exp"]) <= int(self._utc_now().timestamp()):
                raise AccessTokenError("token expired")
            return UUID(str(payload["sub"]))
        except (AccessTokenError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            if isinstance(exc, AccessTokenError):
                raise
            raise AccessTokenError("malformed token") from exc

    def _signature(self, encoded: str) -> str:
        digest = hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def _utc_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now.astimezone(UTC)


class PasswordService:
    """Argon2id password hashing and verification."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=2)

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


class AuthTokens:
    def __init__(self, *, access_token: str, refresh_token: str, expires_in: int) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_in = expires_in


class AuthService:
    def __init__(
        self,
        *,
        repository: AuthRepository,
        access_tokens: AccessTokenCodec,
        refresh_token_pepper: str,
        refresh_ttl_seconds: int = 2_592_000,
        password_service: PasswordService | None = None,
        token_factory: Callable[[], str] = lambda: token_urlsafe(48),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not refresh_token_pepper:
            raise ValueError("refresh token pepper must not be empty")
        if refresh_ttl_seconds < 300:
            raise ValueError("refresh token ttl must be at least 300 seconds")
        self._repository = repository
        self._access_tokens = access_tokens
        self._refresh_pepper = refresh_token_pepper.encode("utf-8")
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._passwords = password_service or PasswordService()
        self._token_factory = token_factory
        self._clock = clock

    async def register(self, *, email: str, password: str, display_name: str) -> tuple[User, AuthTokens]:
        normalized_email = self._normalize_email(email)
        normalized_name = self._normalize_name(display_name)
        self._validate_password(password)
        if await self._repository.get_user_by_email(normalized_email) is not None:
            raise DuplicateEmailError("该邮箱已注册。")
        now = self._now()
        user = User(
            id=uuid4(),
            email=normalized_email,
            display_name=normalized_name,
            password_hash=self._passwords.hash(password),
            status=UserStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        await self._repository.add_user(user)
        return user, await self._issue_tokens(user)

    async def login(self, *, email: str, password: str) -> tuple[User, AuthTokens]:
        user = await self._repository.get_user_by_email(self._normalize_email(email))
        if user is None or not self._passwords.verify(user.password_hash, password):
            raise InvalidCredentialsError("邮箱或密码错误。")
        if not user.is_active:
            raise UserDisabledError("账号已停用，请联系管理员。")
        return user, await self._issue_tokens(user)

    async def refresh(self, *, raw_refresh_token: str) -> tuple[User, AuthTokens]:
        token = await self._repository.get_refresh_token(self._hash_refresh(raw_refresh_token))
        if token is None or token.revoked_at is not None or token.expires_at <= self._now():
            raise InvalidRefreshTokenError("刷新令牌无效或已过期。")
        user = await self._repository.get_user(token.user_id)
        if user is None:
            raise UserNotFoundError("用户不存在。")
        if not user.is_active:
            raise UserDisabledError("账号已停用，请联系管理员。")
        await self._repository.revoke_refresh_token(token.id, self._now())
        return user, await self._issue_tokens(user)

    async def logout(self, *, raw_refresh_token: str) -> None:
        token = await self._repository.get_refresh_token(self._hash_refresh(raw_refresh_token))
        if token is not None and token.revoked_at is None:
            await self._repository.revoke_refresh_token(token.id, self._now())

    async def get_user(self, user_id: UUID) -> User:
        user = await self._repository.get_user(user_id)
        if user is None:
            raise UserNotFoundError("用户不存在。")
        if not user.is_active:
            raise UserDisabledError("账号已停用，请联系管理员。")
        return user

    async def _issue_tokens(self, user: User) -> AuthTokens:
        raw_refresh = self._token_factory()
        now = self._now()
        await self._repository.add_refresh_token(
            RefreshToken(
                id=uuid4(),
                user_id=user.id,
                token_hash=self._hash_refresh(raw_refresh),
                created_at=now,
                expires_at=now + timedelta(seconds=self._refresh_ttl_seconds),
            )
        )
        return AuthTokens(
            access_token=self._access_tokens.issue(user.id),
            refresh_token=raw_refresh,
            expires_in=self._access_tokens._ttl_seconds,
        )

    def _hash_refresh(self, raw_token: str) -> str:
        return hmac.new(self._refresh_pepper, raw_token.encode("utf-8"), hashlib.sha256).hexdigest()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = email.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise InvalidCredentialsError("邮箱格式无效。")
        return normalized

    @staticmethod
    def _normalize_name(display_name: str) -> str:
        normalized = display_name.strip()
        if not normalized or len(normalized) > 120:
            raise ValueError("display_name must contain 1 to 120 characters")
        return normalized

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 8 or len(password) > 128:
            raise ValueError("password must contain 8 to 128 characters")
