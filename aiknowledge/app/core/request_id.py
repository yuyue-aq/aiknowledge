from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID, uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


REQUEST_ID_HEADER = "X-Request-ID"
_request_id: ContextVar[str] = ContextVar("request_id", default="")


def current_request_id() -> str:
    """Return the correlation ID established by the outer request middleware."""

    return _request_id.get()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a validated correlation ID to every HTTP request and response."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        request_id = self._resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = _request_id.set(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            _request_id.reset(token)

    @staticmethod
    def _resolve_request_id(candidate: str | None) -> str:
        if candidate:
            try:
                return str(UUID(candidate))
            except (ValueError, AttributeError):
                pass
        return str(uuid4())
