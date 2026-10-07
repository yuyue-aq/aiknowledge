from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.spaces import KnowledgeSpace
from app.domain.users import SpaceMembership, SpaceRole, User
from app.infrastructure.database.models import (
    KnowledgeSpaceRecord,
    SpaceMembershipRecord,
    UserRecord,
)


class SqlAlchemyMembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_space(self, space_id: UUID) -> KnowledgeSpace | None:
        record = await self._session.get(KnowledgeSpaceRecord, space_id)
        if record is None:
            return None
        return KnowledgeSpace(
            id=record.id,
            name=record.name,
            description=record.description,
            visibility=record.visibility,
            guest_feedback_enabled=record.guest_feedback_enabled,
            plan=record.plan,
            kind=record.kind,
            created_at=record.created_at,
            updated_at=record.updated_at,
            deleted_at=record.deleted_at,
            owner_user_id=record.owner_user_id,
        )

    async def get_user(self, user_id: UUID) -> User | None:
        record = await self._session.get(UserRecord, user_id)
        return self._to_user(record) if record is not None else None

    async def get_user_by_email(self, email: str) -> User | None:
        record = await self._session.scalar(select(UserRecord).where(UserRecord.email == email))
        return self._to_user(record) if record is not None else None

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
    def _to_membership(record: SpaceMembershipRecord) -> SpaceMembership:
        return SpaceMembership(
            space_id=record.space_id,
            user_id=record.user_id,
            role=record.role,
            created_at=record.created_at,
        )
