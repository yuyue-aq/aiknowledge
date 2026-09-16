from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infrastructure.health import DependencyUnavailable


class AsyncRedisClient(Protocol):
    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


class RedisReadinessProbe:
    """Ping Redis through a short-lived async client and always close it."""

    def __init__(
        self,
        *,
        url: str,
        client_factory: Callable[[str], AsyncRedisClient] | None = None,
    ) -> None:
        self._url = url
        self._client_factory = client_factory or self._create_client

    async def check(self) -> None:
        client = self._client_factory(self._url)
        try:
            await client.ping()
        except RedisError as exc:
            raise DependencyUnavailable("Redis is unavailable.") from exc
        finally:
            await client.aclose()

    @staticmethod
    def _create_client(url: str) -> Redis:
        return Redis.from_url(url)
