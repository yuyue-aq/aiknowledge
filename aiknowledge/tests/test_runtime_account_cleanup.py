from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.users import UserStatus
from app.infrastructure.database.models import RefreshTokenRecord, UserRecord


spec = importlib.util.spec_from_file_location(
    "runtime_account_cleanup",
    Path(__file__).resolve().parents[2] / "ops" / "disable_runtime_accounts.py",
)
assert spec is not None and spec.loader is not None
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class AsyncSessionAdapter:
    """Exercise the cleanup's SQL against a real, isolated SQLite database."""

    def __init__(self, session: Session) -> None:
        self.session = session

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def execute(self, statement):
        return self.session.execute(statement)

    async def flush(self) -> None:
        self.session.flush()


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    UserRecord.__table__.create(engine)
    RefreshTokenRecord.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_user(session: Session, *, email: str | None = None, name: str = "Runtime E2E"):
    user = UserRecord(
        id=uuid4(),
        email=email or f"aiknowledge-runtime-{uuid4().hex}@example.invalid",
        display_name=name,
        password_hash="unused-test-hash",
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    session.flush()
    token = RefreshTokenRecord(
        id=uuid4(),
        user_id=user.id,
        token_hash=uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    session.add(token)
    session.flush()
    return user, token


@pytest.mark.asyncio
async def test_cleanup_disables_only_matched_user_and_revokes_their_sessions(session):
    target, token = add_user(session)
    other, other_token = add_user(session)

    assert await cleanup.disable_account(
        AsyncSessionAdapter(session), email=target.email, user_id=target.id
    )
    session.expire_all()

    assert target.status is UserStatus.DISABLED
    assert token.revoked_at is not None
    assert other.status is UserStatus.ACTIVE
    assert other_token.revoked_at is None


@pytest.mark.asyncio
async def test_cleanup_requires_matching_id_email_and_test_display_name(session):
    target, token = add_user(session)
    other, _ = add_user(session)
    ordinary, _ = add_user(session, name="Real user")

    for user_id, email in [(other.id, target.email), (ordinary.id, ordinary.email)]:
        assert not await cleanup.disable_account(
            AsyncSessionAdapter(session), email=email, user_id=user_id
        )

    assert target.status is UserStatus.ACTIVE
    assert ordinary.status is UserStatus.ACTIVE
    assert token.revoked_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["owner@example.com", cleanup.LEGACY_EMAIL])
async def test_generated_account_mode_rejects_non_generated_identities(session, email):
    user, token = add_user(session, email=email)

    with pytest.raises(ValueError):
        await cleanup.disable_account(
            AsyncSessionAdapter(session), email=user.email, user_id=user.id
        )

    assert user.status is UserStatus.ACTIVE
    assert token.revoked_at is None


@pytest.mark.asyncio
async def test_legacy_cleanup_is_narrow_and_idempotent(session):
    legacy, token = add_user(session, email=cleanup.LEGACY_EMAIL)
    other, _ = add_user(session)
    adapter = AsyncSessionAdapter(session)

    assert await cleanup.disable_account(adapter, email=legacy.email, legacy=True)
    session.expire_all()
    revoked_at = token.revoked_at
    assert await cleanup.disable_account(adapter, email=legacy.email, legacy=True)
    session.expire_all()

    assert legacy.status is UserStatus.DISABLED
    assert token.revoked_at == revoked_at
    assert other.status is UserStatus.ACTIVE
    with pytest.raises(ValueError):
        await cleanup.disable_account(adapter, email=other.email, legacy=True)
    with pytest.raises(ValueError):
        await cleanup.disable_account(adapter, email=legacy.email, user_id=UUID(int=1), legacy=True)


@pytest.mark.asyncio
async def test_absent_legacy_account_needs_no_changes(session):
    assert not await cleanup.disable_account(
        AsyncSessionAdapter(session), email=cleanup.LEGACY_EMAIL, legacy=True
    )
