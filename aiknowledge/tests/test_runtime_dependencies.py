from __future__ import annotations

import pytest
from redis.exceptions import RedisError

from app.infrastructure.health import (
    CompositeReadinessProbe,
    DependencyUnavailable,
    ObjectStorageReadinessProbe,
)
from app.infrastructure.queue.redis import RedisReadinessProbe
from app.infrastructure.storage.minio import ObjectStorageError
from app.workers.celery_app import create_celery
from app.workers.tasks import register_core_tasks


class FakeRedisClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.pinged = False
        self.closed = False

    async def ping(self) -> bool:
        self.pinged = True
        if self.error is not None:
            raise self.error
        return True

    async def aclose(self) -> None:
        self.closed = True


class FakeStorage:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def ensure_bucket(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


class RecordingProbe:
    def __init__(self, calls: list[str], name: str) -> None:
        self.calls = calls
        self.name = name

    async def check(self) -> None:
        self.calls.append(self.name)


@pytest.mark.asyncio
async def test_redis_readiness_pings_and_closes_the_async_client() -> None:
    client = FakeRedisClient()
    probe = RedisReadinessProbe(
        url="redis://localhost:6379/0", client_factory=lambda _: client
    )

    await probe.check()

    assert client.pinged is True
    assert client.closed is True


@pytest.mark.asyncio
async def test_redis_readiness_sanitizes_upstream_errors_and_still_closes_client() -> None:
    client = FakeRedisClient(error=RedisError("sensitive redis endpoint"))
    probe = RedisReadinessProbe(
        url="redis://localhost:6379/0", client_factory=lambda _: client
    )

    with pytest.raises(DependencyUnavailable) as error:
        await probe.check()

    assert "sensitive redis endpoint" not in str(error.value)
    assert client.closed is True


@pytest.mark.asyncio
async def test_storage_readiness_bootstraps_the_private_bucket_and_sanitizes_failure() -> None:
    storage = FakeStorage(error=ObjectStorageError("sensitive credentials"))
    probe = ObjectStorageReadinessProbe(storage)

    with pytest.raises(DependencyUnavailable) as error:
        await probe.check()

    assert storage.calls == 1
    assert "sensitive credentials" not in str(error.value)


@pytest.mark.asyncio
async def test_composite_readiness_checks_every_dependency_in_a_deterministic_order() -> None:
    calls: list[str] = []
    probe = CompositeReadinessProbe(
        RecordingProbe(calls, "database"),
        RecordingProbe(calls, "redis"),
        RecordingProbe(calls, "storage"),
    )

    await probe.check()

    assert calls == ["database", "redis", "storage"]


def test_celery_health_task_can_complete_in_eager_test_mode_without_redis() -> None:
    celery = create_celery(
        broker_url="memory://",
        result_backend="cache+memory://",
    )
    celery.conf.update(task_always_eager=True, task_store_eager_result=True)
    health_task = register_core_tasks(celery)

    result = health_task.delay().get(timeout=1)

    assert result == {"status": "ok"}
    assert celery.conf.task_serializer == "json"
    assert celery.conf.result_serializer == "json"
    assert celery.conf.accept_content == ["json"]
