from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infrastructure.database.session import Database
from app.domain.users import User, UserDisabledError, UserNotFoundError
from app.services.auth import AccessTokenError


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Own one transaction per API request without holding it during streams."""

    database: Database = request.app.state.database
    async with database.session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Resolve and validate the short-lived bearer token for owner APIs."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            code="AUTHENTICATION_REQUIRED",
            message="请先登录。",
            status_code=401,
        )
    return await _resolve_user(request, session, credentials)


async def get_optional_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User | None:
    """Allow legacy local fixtures while enforcing auth in configured deployments."""

    if credentials is None:
        if request.app.state.settings.auth_required:
            raise AppError(
                code="AUTHENTICATION_REQUIRED",
                message="请先登录。",
                status_code=401,
            )
        return None
    if credentials.scheme.lower() != "bearer":
        raise AppError(code="INVALID_ACCESS_TOKEN", message="登录状态已失效，请重新登录。", status_code=401)
    return await _resolve_user(request, session, credentials)


async def _resolve_user(
    request: Request,
    session: AsyncSession,
    credentials: HTTPAuthorizationCredentials,
) -> User:
    codec = request.app.state.access_token_codec
    try:
        user_id = codec.verify(credentials.credentials)
    except AccessTokenError as exc:
        raise AppError(
            code="INVALID_ACCESS_TOKEN",
            message="登录状态已失效，请重新登录。",
            status_code=401,
        ) from exc
    try:
        return await request.app.state.auth_service_factory(session).get_user(user_id)
    except (UserNotFoundError, UserDisabledError) as exc:
        raise AppError(
            code="AUTHENTICATION_REQUIRED",
            message="请先登录。",
            status_code=401,
        ) from exc
