from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.sources import KnowledgeSource
from app.domain.users import SpaceRole
from app.infrastructure.database.models import (
    KnowledgeSourceRecord,
    KnowledgeSpaceRecord,
    SpaceMembershipRecord,
)


class SqlAlchemySourceRepository:
    """Persistence adapter for registered external knowledge sources."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        space = await self._session.scalar(
            select(KnowledgeSpaceRecord).where(
                KnowledgeSpaceRecord.id == space_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
        )
        if space is None:
            return None
        if space.owner_user_id == user_id:
            return SpaceRole.OWNER
        return await self._session.scalar(
            select(SpaceMembershipRecord.role).where(
                SpaceMembershipRecord.space_id == space_id,
                SpaceMembershipRecord.user_id == user_id,
            )
        )

    async def add_source(self, source: KnowledgeSource) -> None:
        self._session.add(
            KnowledgeSourceRecord(
                id=source.id,
                space_id=source.space_id,
                kind=source.kind,
                locator=source.locator,
                name=source.name,
                status=source.status,
                last_checksum=source.last_checksum,
                last_synced_at=source.last_synced_at,
                last_error=source.last_error,
                created_at=source.created_at,
                updated_at=source.updated_at,
            )
        )
        await self._session.flush()

    async def list_sources(self, space_id: UUID) -> list[KnowledgeSource]:
        records = await self._session.scalars(
            select(KnowledgeSourceRecord)
            .where(KnowledgeSourceRecord.space_id == space_id)
            .order_by(KnowledgeSourceRecord.updated_at.desc())
        )
        return [self._to_domain(record) for record in records.all()]

    async def get_source(self, source_id: UUID) -> KnowledgeSource | None:
        record = await self._session.get(KnowledgeSourceRecord, source_id)
        return self._to_domain(record) if record is not None else None

    async def update_source(self, source: KnowledgeSource) -> None:
        record = await self._session.get(KnowledgeSourceRecord, source.id)
        if record is None:
            return
        record.kind = source.kind
        record.locator = source.locator
        record.name = source.name
        record.status = source.status
        record.last_checksum = source.last_checksum
        record.last_synced_at = source.last_synced_at
        record.last_error = source.last_error
        record.updated_at = source.updated_at
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    @staticmethod
    def _to_domain(record: KnowledgeSourceRecord) -> KnowledgeSource:
        return KnowledgeSource(
            id=record.id,
            space_id=record.space_id,
            kind=record.kind,
            locator=record.locator,
            name=record.name,
            status=record.status,
            last_checksum=record.last_checksum,
            last_synced_at=record.last_synced_at,
            last_error=record.last_error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
