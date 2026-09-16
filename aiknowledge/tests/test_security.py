from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from app.core.security import (
    InMemoryRateLimiter,
    OriginProtectionMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)


def _protected_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(OriginProtectionMiddleware, allowed_origins={"http://trusted.test"})
    app.add_middleware(SecurityHeadersMiddleware)

    @app.post("/api/v1/write")
    async def write() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.mark.asyncio
async def test_untrusted_origin_is_rejected_and_security_headers_are_present() -> None:
    app = _protected_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/write", headers={"origin": "https://evil.test"}
        )

    assert response.status_code == 403
    assert response.json()["code"] == "ORIGIN_NOT_ALLOWED"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_safe_request_without_origin_remains_usable() -> None:
    app = _protected_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_rate_limiter_allows_limit_then_returns_retryable_429() -> None:
    app = FastAPI()
    limiter = InMemoryRateLimiter(window_seconds=60)
    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter,
        limits={"public_session": 1},
    )

    @app.post("/api/v1/public/session")
    async def session() -> dict[str, str]:
        return {"status": "ok"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = await client.post("/api/v1/public/session")
        second = await client.post("/api/v1/public/session")

    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "1"
    assert first.headers["x-ratelimit-remaining"] == "0"
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"
    assert second.headers["retry-after"] == "60"
