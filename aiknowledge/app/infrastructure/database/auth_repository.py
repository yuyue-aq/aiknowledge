from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.users import RefreshToken, SpaceMembership, User
from app.infrastructure.database.models import (
    RefreshTokenRecord,
    SpaceMembershipRecord,
    UserRecord,
)


class SqlAlchemyAuthRepository:
    """Persistence adapter for users and revocable refresh sessions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email(self, email: str) -> User | None:
        record = await self._session.scalar(select(UserRecord).where(UserRecord.email == email))
        return self._to_user(record) if record is not None else None

    async def get_user(self, user_id: UUID) -> User | None:
        record = await self._session.get(UserRecord, user_id)
        return self._to_user(record) if record is not None else None

    async def add_user(self, user: User) -> None:
        self._session.add(
            UserRecord(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                password_hash=user.password_hash,
                status=user.status,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
        )
        await self._session.flush()

    async def add_refresh_token(self, token: RefreshToken) -> None:
        self._session.add(
            RefreshTokenRecord(
                id=token.id,
                user_id=token.user_id,
                token_hash=token.token_hash,
                created_at=token.created_at,
                expires_at=token.expires_at,
                revoked_at=token.revoked_at,
            )
        )
        await self._session.flush()

    async def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        record = await self._session.scalar(
            select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == token_hash)
        )
        return self._to_refresh_token(record) if record is not None else None

    async def revoke_refresh_token(self, token_id: UUID, revoked_at: datetime) -> None:
        await self._session.execute(
            update(RefreshTokenRecord)
            .where(RefreshTokenRecord.id == token_id, RefreshTokenRecord.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
        await self._session.flush()

    async def get_membership(self, *, space_id: UUID, user_id: UUID) -> SpaceMembership | None:
        record = await self._session.get(
            SpaceMembershipRecord, {"space_id": space_id, "user_id": user_id}
        )
        return self._to_membership(record) if record is not None else None

    async def list_memberships(self, space_id: UUID) -> list[SpaceMembership]:
        records = await self._session.scalars(
            select(SpaceMembershipRecord)
            .where(SpaceMembershipRecord.space_id == space_id)
            .order_by(SpaceMembershipRecord.created_at)
        )
        return [self._to_membership(record) for record in records.all()]

    async def add_membership(self, membership: SpaceMembership) -> None:
        self._session.add(
            SpaceMembershipRecord(
                space_id=membership.space_id,
                user_id=membership.user_id,
                role=membership.role,
                created_at=membership.created_at,
            )
        )
        await self._session.flush()

    async def update_membership(self, membership: SpaceMembership) -> None:
        record = await self._session.get(
            SpaceMembershipRecord,
            {"space_id": membership.space_id, "user_id": membership.user_id},
        )
        if record is None:
            return
        record.role = membership.role
        await self._session.flush()

    async def delete_membership(self, *, space_id: UUID, user_id: UUID) -> None:
        record = await self._session.get(
            SpaceMembershipRecord, {"space_id": space_id, "user_id": user_id}
        )
        if record is not None:
            await self._session.delete(record)
            await self._session.flush()

    @staticmethod
    def _to_user(record: UserRecord) -> User:
        return User(
            id=record.id,
            email=record.email,
            display_name=record.display_name,
            password_hash=record.password_hash,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_refresh_token(record: RefreshTokenRecord) -> RefreshToken:
        return RefreshToken(
            id=record.id,
            user_id=record.user_id,
            token_hash=record.token_hash,
            created_at=record.created_at,
            expires_at=record.expires_at,
            revoked_at=record.revoked_at,
        )

    @staticmethod
    def _to_membership(record: SpaceMembershipRecord) -> SpaceMembership:
        return SpaceMembership(
            space_id=record.space_id,
            user_id=record.user_id,
            role=record.role,
            created_at=record.created_at,
        )
