from __future__ import annotations

from uuid import UUID

import httpx
import pytest

from app.infrastructure.database.session import Database
from app.infrastructure.health import DependencyUnavailable
from app.main import create_app


class HealthyProbe:
    def __init__(self) -> None:
        self.calls = 0

    async def check(self) -> None:
        self.calls += 1


class UnhealthyProbe:
    async def check(self) -> None:
        raise DependencyUnavailable("A required service is not ready.")


@pytest.mark.asyncio
async def test_ready_health_check_uses_the_injected_dependency_probe() -> None:
    probe = HealthyProbe()
    app = create_app(rag_service=object(), readiness_probe=probe)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert probe.calls == 1
    assert UUID(response.headers["x-request-id"])
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_ready_health_check_uses_the_standard_error_protocol_when_unready() -> None:
    request_id = "f1c245f8-1dd1-4b9d-8e96-6d8229fb17d4"
    app = create_app(rag_service=object(), readiness_probe=UnhealthyProbe())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/health/ready", headers={"X-Request-ID": request_id}
        )

    assert response.status_code == 503
    assert response.headers["x-request-id"] == request_id
    assert response.json() == {
        "code": "DEPENDENCY_NOT_READY",
        "message": "服务暂时不可用，请稍后重试。",
        "request_id": request_id,
        "details": None,
    }


@pytest.mark.asyncio
async def test_validation_errors_do_not_echo_request_content_and_keep_request_id() -> None:
    request_id = "f1c245f8-1dd1-4b9d-8e96-6d8229fb17d4"
    app = create_app(rag_service=object(), readiness_probe=HealthyProbe())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/model/answer",
            headers={"X-Request-ID": request_id},
            json={"question": "不应泄漏到错误响应的内容", "documents": []},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "REQUEST_VALIDATION_FAILED"
    assert body["request_id"] == request_id
    assert "不应泄漏到错误响应的内容" not in str(body)
    assert body["details"] == [
        {
            "loc": ["body", "documents"],
            "msg": "List should have at least 1 item after validation, not 0",
            "type": "too_short",
        }
    ]


@pytest.mark.asyncio
async def test_application_rejects_untrusted_browser_origin_before_route_execution() -> None:
    app = create_app(rag_service=object(), readiness_probe=HealthyProbe())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/model/answer",
            headers={"origin": "https://evil.test"},
            json={"question": "should not execute", "documents": ["evidence"]},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "ORIGIN_NOT_ALLOWED"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_database_requires_the_asyncpg_postgresql_driver() -> None:
    database = Database(
        url="postgresql+asyncpg://aiknowledge:aiknowledge@localhost:5432/aiknowledge",
        pool_size=2,
        max_overflow=3,
    )

    assert database.engine.url.drivername == "postgresql+asyncpg"
    assert database.engine.url.database == "aiknowledge"

    with pytest.raises(ValueError, match="postgresql\\+asyncpg"):
        Database(url="postgresql://localhost/aiknowledge")
