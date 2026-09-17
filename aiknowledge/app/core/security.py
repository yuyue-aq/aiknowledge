from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.request_id import current_request_id


_SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
_PUBLIC_SESSION_PATH = "/api/v1/public/session"
_PUBLIC_QUESTION_PREFIX = "/api/v1/public/conversations/"
_PUBLIC_QUERY_PATH = "/api/v1/public/query"


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class InMemoryRateLimiter:
    """Small-process limiter for anonymous endpoints.

    This intentionally has no distributed-storage dependency.  Deployments
    with more than one API process should replace it with a shared Redis
    implementation while keeping the middleware contract unchanged.
    """

    def __init__(
        self,
        *,
        window_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: defaultdict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, *, bucket: str, key: str, limit: int) -> RateLimitDecision:
        if limit <= 0:
            raise ValueError("limit must be positive")
        now = self._clock()
        cutoff = now - self.window_seconds
        event_key = (bucket, key)
        async with self._lock:
            events = self._events[event_key]
            while events and events[0] <= cutoff:
                events.popleft()
            allowed = len(events) < limit
            if allowed:
                events.append(now)
            remaining = max(0, limit - len(events))
            retry_after = 0
            if not allowed and events:
                retry_after = max(1, int(events[0] + self.window_seconds - now + 0.999))
            return RateLimitDecision(
                allowed=allowed,
                limit=limit,
                remaining=remaining,
                retry_after_seconds=retry_after,
            )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Limit public session creation and anonymous question submissions."""

    def __init__(
        self,
        app,
        *,
        limiter: InMemoryRateLimiter,
        limits: dict[str, int],
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._limits = dict(limits)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        bucket = self._bucket_for(request)
        limit = self._limits.get(bucket) if bucket else None
        if bucket is None or limit is None:
            return await call_next(request)

        host = request.client.host if request.client is not None else "unknown"
        decision = await self._limiter.check(bucket=bucket, key=host, limit=limit)
        headers = {
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
        }
        if not decision.allowed:
            headers["Retry-After"] = str(decision.retry_after_seconds)
            return JSONResponse(
                status_code=429,
                content={
                    "code": "RATE_LIMITED",
                    "message": "请求过于频繁，请稍后重试。",
                    "request_id": current_request_id(),
                    "details": None,
                },
                headers=headers,
            )
        response = await call_next(request)
        for name, value in headers.items():
            response.headers[name] = value
        return response

    @staticmethod
    def _bucket_for(request: Request) -> str | None:
        if request.method != "POST":
            return None
        if request.url.path == _PUBLIC_SESSION_PATH:
            return "public_session"
        if (
            request.url.path.startswith(_PUBLIC_QUESTION_PREFIX)
            and request.url.path.endswith("/messages")
        ):
            return "public_question"
        if request.url.path == _PUBLIC_QUERY_PATH:
            return "public_question"
        return None


class OriginProtectionMiddleware(BaseHTTPMiddleware):
    """Reject state-changing browser calls from untrusted origins.

    Requests without an Origin header remain valid for native clients and
    command-line smoke tests.  Browser requests must exactly match one of the
    configured origins; wildcard origins are deliberately not accepted.
    """

    def __init__(self, app, *, allowed_origins: Iterable[str]) -> None:
        super().__init__(app)
        self._allowed_origins = frozenset(
            origin.strip().rstrip("/")
            for origin in allowed_origins
            if origin.strip() and origin.strip() != "*"
        )

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        origin = request.headers.get("origin")
        if (
            origin
            and request.method not in _SAFE_METHODS
            and request.url.path.startswith("/api/v1/")
            and origin.rstrip("/") not in self._allowed_origins
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "code": "ORIGIN_NOT_ALLOWED",
                    "message": "请求来源不受信任。",
                    "request_id": current_request_id(),
                    "details": None,
                },
            )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach browser hardening headers to every API response."""

    _HEADERS: Final = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'self'",
    }

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response = await call_next(request)
        for name, value in self._HEADERS.items():
            response.headers[name] = value
        return response
