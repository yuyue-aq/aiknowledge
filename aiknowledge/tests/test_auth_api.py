from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain.users import DuplicateEmailError, User, UserStatus
from app.main import create_app
from app.services.auth import AccessTokenCodec, AuthTokens


class FakeAuthService:
    def __init__(self) -> None:
        now = datetime(2026, 9, 17, tzinfo=UTC)
        self.user = User(
            id=uuid4(),
            email="user@example.com",
            display_name="用户",
            password_hash="$argon2id$test",
            status=UserStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

    async def register(self, **kwargs: object) -> tuple[User, AuthTokens]:
        if kwargs["email"] == "duplicate@example.com":
            raise DuplicateEmailError("duplicate")
        return self.user, AuthTokens(access_token="access", refresh_token="refresh", expires_in=900)

    async def login(self, **_: object) -> tuple[User, AuthTokens]:
        return self.user, AuthTokens(access_token="access", refresh_token="refresh", expires_in=900)

    async def refresh(self, **_: object) -> tuple[User, AuthTokens]:
        return self.user, AuthTokens(access_token="access-2", refresh_token="refresh-2", expires_in=900)

    async def logout(self, **_: object) -> None:
        return None

    async def get_user(self, user_id: UUID) -> User:
        assert user_id == self.user.id
        return self.user


@pytest.mark.asyncio
async def test_auth_api_register_returns_user_and_tokens() -> None:
    service = FakeAuthService()
    app = create_app(rag_service=object(), auth_service_factory=lambda _: service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": "password-123", "display_name": "用户"},
        )

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "user@example.com"
    assert response.json()["tokens"]["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_auth_api_maps_duplicate_email_and_protects_me() -> None:
    service = FakeAuthService()
    app = create_app(rag_service=object(), auth_service_factory=lambda _: service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        duplicate = await client.post(
            "/api/v1/auth/register",
            json={"email": "duplicate@example.com", "password": "password-123", "display_name": "用户"},
        )
        missing = await client.get("/api/v1/auth/me")

    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "EMAIL_ALREADY_REGISTERED"
    assert missing.status_code == 401
    assert missing.json()["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_auth_api_me_resolves_signed_bearer_token() -> None:
    service = FakeAuthService()
    app = create_app(rag_service=object(), auth_service_factory=lambda _: service)
    token = app.state.access_token_codec.issue(service.user.id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["id"] == str(service.user.id)
