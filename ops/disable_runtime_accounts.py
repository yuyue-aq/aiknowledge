"""Disable only identified smoke-test accounts and revoke their refresh tokens."""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
import re
import sys
from uuid import UUID


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "aiknowledge"
if BACKEND_ROOT.is_dir():
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.domain.users import UserStatus
from app.infrastructure.database.models import RefreshTokenRecord, UserRecord


LEGACY_EMAIL = "aiknowledge-runtime-e2e@example.invalid"
RUNTIME_EMAIL = re.compile(r"aiknowledge-runtime-[0-9a-f]{32}@example\.invalid")


async def disable_account(
    session: AsyncSession, *, email: str, user_id: UUID | None = None, legacy: bool = False
) -> bool:
    if legacy:
        if email != LEGACY_EMAIL or user_id is not None:
            raise ValueError("Legacy cleanup requires the exact legacy identity.")
    elif user_id is None or RUNTIME_EMAIL.fullmatch(email) is None:
        raise ValueError("Cleanup requires a runtime test user ID and generated email.")

    statement = select(UserRecord).where(
        UserRecord.email == email, UserRecord.display_name == "Runtime E2E"
    )
    if user_id is not None:
        statement = statement.where(UserRecord.id == user_id)
    user = await session.scalar(statement)
    if user is None:
        return False

    now = datetime.now(UTC)
    user.status = UserStatus.DISABLED
    user.updated_at = now
    await session.execute(
        update(RefreshTokenRecord)
        .where(RefreshTokenRecord.user_id == user.id, RefreshTokenRecord.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await session.flush()
    return True


async def run(args: argparse.Namespace) -> int:
    settings = Settings(_env_file=BACKEND_ROOT / ".env") if BACKEND_ROOT.is_dir() else Settings()
    engine = create_async_engine(settings.database_url, connect_args={"timeout": 10})
    try:
        async with async_sessionmaker(engine)() as session:
            disabled = await disable_account(
                session,
                email=LEGACY_EMAIL if args.legacy else args.email,
                user_id=args.user_id,
                legacy=args.legacy,
            )
            await session.commit()
        print(f"runtime_account_disabled={str(disabled).lower()}")
        # An absent legacy account is already clean. A per-run identity mismatch
        # is a failure, so smoke tests cannot claim successful account cleanup.
        return 0 if disabled or args.legacy else 1
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--legacy", action="store_true")
    mode.add_argument("--user-id", type=UUID)
    parser.add_argument("--email")
    args = parser.parse_args()
    if args.legacy and args.email is not None:
        parser.error("--legacy cannot be combined with --email")
    if not args.legacy and (not args.email or RUNTIME_EMAIL.fullmatch(args.email) is None):
        parser.error("--user-id requires a generated runtime test --email")
    try:
        return asyncio.run(run(args))
    except Exception:
        # Driver exceptions can include connection details. Keep them out of
        # logs and leave the transaction uncommitted on failure.
        print("Runtime account cleanup failed; check database availability and configuration.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
