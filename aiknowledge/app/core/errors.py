from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from app.core.request_id import current_request_id


class AppError(Exception):
    """A public, stable error that must not contain private input or secrets."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: object | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def app_error_response(_: Request, error: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "code": error.code,
            "message": error.message,
            "request_id": current_request_id(),
            "details": error.details,
        },
    )


def validation_error_response(_: Request, error: RequestValidationError) -> JSONResponse:
    """Expose field locations, not user-provided values, in validation errors."""

    details: list[dict[str, Any]] = []
    for item in error.errors():
        details.append(
            {
                "loc": list(item.get("loc", ())),
                "msg": item.get("msg", "Invalid request."),
                "type": item.get("type", "value_error"),
            }
        )
    return JSONResponse(
        status_code=422,
        content={
            "code": "REQUEST_VALIDATION_FAILED",
            "message": "请求参数无效。",
            "request_id": current_request_id(),
            "details": details,
        },
    )


def unhandled_error_response(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "服务暂时不可用，请稍后重试。",
            "request_id": current_request_id(),
            "details": None,
        },
    )
