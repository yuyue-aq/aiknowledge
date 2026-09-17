from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.domain.users import (
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    RefreshToken,
    User,
    UserStatus,
)
from app.services.auth import AccessTokenCodec, AccessTokenError, AuthService


class FakeAuthRepository:
    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}

    async def get_user_by_email(self, email: str) -> User | None:
        return next((u for u in self.users.values() if u.email == email), None)

    async def get_user(self, user_id: UUID) -> User | None:
        return self.users.get(user_id)

    async def add_user(self, user: User) -> None:
        self.users[user.id] = user

    async def add_refresh_token(self, token: RefreshToken) -> None:
        self.refresh_tokens[token.token_hash] = token

    async def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        return next((t for t in self.refresh_tokens.values() if t.token_hash == token_hash), None)

    async def revoke_refresh_token(self, token_id: UUID, revoked_at: datetime) -> None:
        for key, token in self.refresh_tokens.items():
            if token.id == token_id:
                self.refresh_tokens[key] = RefreshToken(
                    id=token.id,
                    user_id=token.user_id,
                    token_hash=token.token_hash,
                    created_at=token.created_at,
                    expires_at=token.expires_at,
                    revoked_at=revoked_at,
                )


@pytest.fixture
def clock() -> list[datetime]:
    return [datetime(2026, 9, 17, 12, 0, tzinfo=UTC)]


def make_service(repo: FakeAuthRepository, clock: list[datetime]) -> AuthService:
    now = lambda: clock[0]
    return AuthService(
        repository=repo,
        access_tokens=AccessTokenCodec(secret="access-secret", ttl_seconds=900, clock=now),
        refresh_token_pepper="refresh-secret",
        refresh_ttl_seconds=3600,
        token_factory=lambda: "refresh-raw-token",
        clock=now,
    )


@pytest.mark.asyncio
async def test_register_hashes_password_normalizes_identity_and_returns_tokens(clock: list[datetime]) -> None:
    repo = FakeAuthRepository()
    service = make_service(repo, clock)

    user, tokens = await service.register(
        email="  USER@Example.COM ", password="a-secure-password", display_name="  知识管理员  "
    )

    assert user.email == "user@example.com"
    assert user.display_name == "知识管理员"
    assert user.password_hash.startswith("$argon2id$")
    assert tokens.access_token
    assert tokens.refresh_token == "refresh-raw-token"
    assert len(repo.refresh_tokens) == 1
    assert "refresh-raw-token" not in next(iter(repo.refresh_tokens))


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(clock: list[datetime]) -> None:
    repo = FakeAuthRepository()
    service = make_service(repo, clock)
    await service.register(email="user@example.com", password="password-123", display_name="用户")

    with pytest.raises(DuplicateEmailError):
        await service.register(email="USER@example.com", password="password-456", display_name="另一个用户")


@pytest.mark.asyncio
async def test_login_returns_same_user_and_rejects_bad_password(clock: list[datetime]) -> None:
    repo = FakeAuthRepository()
    service = make_service(repo, clock)
    expected, _ = await service.register(
        email="user@example.com", password="password-123", display_name="用户"
    )

    actual, _ = await service.login(email="USER@example.com", password="password-123")
    assert actual.id == expected.id

    with pytest.raises(InvalidCredentialsError):
        await service.login(email="user@example.com", password="wrong-password")


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_old_token_cannot_be_reused(clock: list[datetime]) -> None:
    repo = FakeAuthRepository()
    token_values = iter(("refresh-first", "refresh-second"))
    now = lambda: clock[0]
    service = AuthService(
        repository=repo,
        access_tokens=AccessTokenCodec(secret="access-secret", ttl_seconds=900, clock=now),
        refresh_token_pepper="refresh-secret",
        refresh_ttl_seconds=3600,
        token_factory=lambda: next(token_values),
        clock=now,
    )
    _, first = await service.register(
        email="user@example.com", password="password-123", display_name="用户"
    )

    _, second = await service.refresh(raw_refresh_token=first.refresh_token)
    assert second.refresh_token != first.refresh_token
    assert any(token.revoked_at is not None for token in repo.refresh_tokens.values())

    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh(raw_refresh_token=first.refresh_token)


def test_access_token_detects_tampering_and_expiry(clock: list[datetime]) -> None:
    codec = AccessTokenCodec(secret="access-secret", ttl_seconds=60, clock=lambda: clock[0])
    user_id = uuid4()
    token = codec.issue(user_id)
    assert codec.verify(token) == user_id

    with pytest.raises(AccessTokenError):
        codec.verify(token + "tampered")

    clock[0] += timedelta(seconds=61)
    with pytest.raises(AccessTokenError):
        codec.verify(token)
