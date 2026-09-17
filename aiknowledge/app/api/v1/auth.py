from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_database_session
from app.core.errors import AppError
from app.domain.users import (
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    User,
    UserDisabledError,
    UserNotFoundError,
)
from app.services.auth import AuthService, AuthTokens


router = APIRouter(prefix="/auth", tags=["auth"])


class AuthServicePort(Protocol):
    async def register(self, *, email: str, password: str, display_name: str) -> tuple[User, AuthTokens]: ...

    async def login(self, *, email: str, password: str) -> tuple[User, AuthTokens]: ...

    async def refresh(self, *, raw_refresh_token: str) -> tuple[User, AuthTokens]: ...

    async def logout(self, *, raw_refresh_token: str) -> None: ...

    async def get_user(self, user_id: UUID) -> User: ...


def get_auth_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> AuthServicePort:
    return request.app.state.auth_service_factory(session)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            status=user.status.value,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

    @classmethod
    def from_domain(cls, tokens: AuthTokens) -> "TokenResponse":
        return cls(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )


class AuthResponse(BaseModel):
    user: UserResponse
    tokens: TokenResponse

    @classmethod
    def from_domain(cls, user: User, tokens: AuthTokens) -> "AuthResponse":
        return cls(user=UserResponse.from_domain(user), tokens=TokenResponse.from_domain(tokens))


def _translate_auth_error(error: Exception) -> None:
    if isinstance(error, DuplicateEmailError):
        raise AppError(code="EMAIL_ALREADY_REGISTERED", message="该邮箱已注册。", status_code=409) from error
    if isinstance(error, (InvalidCredentialsError, InvalidRefreshTokenError)):
        raise AppError(code="INVALID_CREDENTIALS", message="邮箱、密码或刷新令牌错误。", status_code=401) from error
    if isinstance(error, UserDisabledError):
        raise AppError(code="USER_DISABLED", message="账号已停用，请联系管理员。", status_code=403) from error
    if isinstance(error, UserNotFoundError):
        raise AppError(code="USER_NOT_FOUND", message="用户不存在。", status_code=404) from error
    raise error


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    service: Annotated[AuthServicePort, Depends(get_auth_service)],
) -> AuthResponse:
    try:
        user, tokens = await service.register(**payload.model_dump())
    except Exception as error:
        _translate_auth_error(error)
        raise
    return AuthResponse.from_domain(user, tokens)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    service: Annotated[AuthServicePort, Depends(get_auth_service)],
) -> AuthResponse:
    try:
        user, tokens = await service.login(**payload.model_dump())
    except Exception as error:
        _translate_auth_error(error)
        raise
    return AuthResponse.from_domain(user, tokens)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    payload: RefreshRequest,
    service: Annotated[AuthServicePort, Depends(get_auth_service)],
) -> AuthResponse:
    try:
        user, tokens = await service.refresh(raw_refresh_token=payload.refresh_token)
    except Exception as error:
        _translate_auth_error(error)
        raise
    return AuthResponse.from_domain(user, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest,
    service: Annotated[AuthServicePort, Depends(get_auth_service)],
) -> Response:
    await service.logout(raw_refresh_token=payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse.from_domain(current_user)
