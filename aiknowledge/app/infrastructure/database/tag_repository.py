from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tags import KnowledgeTag
from app.infrastructure.database.models import DocumentRecord, TagRecord, document_tags
from app.domain.users import SpaceRole


class SqlAlchemyTagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_tags(self, space_id: UUID) -> list[KnowledgeTag]:
        records = await self._session.scalars(
            select(TagRecord)
            .where(TagRecord.space_id == space_id)
            .order_by(TagRecord.name)
        )
        return [self._to_domain(record) for record in records.all()]

    async def get_tag(self, tag_id: UUID) -> KnowledgeTag | None:
        record = await self._session.get(TagRecord, tag_id)
        return self._to_domain(record) if record is not None else None

    async def find_tag_by_name(self, space_id: UUID, name: str) -> KnowledgeTag | None:
        record = await self._session.scalar(
            select(TagRecord).where(TagRecord.space_id == space_id, TagRecord.name == name)
        )
        return self._to_domain(record) if record is not None else None

    async def add_tag(self, tag: KnowledgeTag) -> None:
        self._session.add(
            TagRecord(
                id=tag.id,
                space_id=tag.space_id,
                name=tag.name,
                color=tag.color,
                created_at=tag.created_at,
                updated_at=tag.updated_at,
            )
        )
        await self._session.flush()

    async def update_tag(self, tag_id: UUID, **changes: object) -> KnowledgeTag | None:
        record = await self._session.get(TagRecord, tag_id, with_for_update=True)
        if record is None:
            return None
        for field, value in changes.items():
            if hasattr(record, field):
                setattr(record, field, value)
        await self._session.flush()
        return self._to_domain(record)

    async def delete_tag(self, tag_id: UUID) -> None:
        await self._session.delete(await self._session.get(TagRecord, tag_id))
        await self._session.flush()

    async def set_document_tags(
        self, document_id: UUID, tag_ids: tuple[UUID, ...]
    ) -> tuple[KnowledgeTag, ...]:
        await self._session.execute(delete(document_tags).where(document_tags.c.document_id == document_id))
        if tag_ids:
            await self._session.execute(
                insert(document_tags),
                [{"document_id": document_id, "tag_id": tag_id} for tag_id in tag_ids],
            )
        return await self.get_document_tags(document_id)

    async def get_document_tags(self, document_id: UUID) -> tuple[KnowledgeTag, ...]:
        records = await self._session.scalars(
            select(TagRecord)
            .join(document_tags, document_tags.c.tag_id == TagRecord.id)
            .where(document_tags.c.document_id == document_id)
            .order_by(TagRecord.name)
        )
        return tuple(self._to_domain(record) for record in records.all())

    async def get_document_space_id(self, document_id: UUID) -> UUID | None:
        return await self._session.scalar(
            select(DocumentRecord.space_id).where(
                DocumentRecord.id == document_id,
                DocumentRecord.deleted_at.is_(None),
            )
        )

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        from app.infrastructure.database.models import KnowledgeSpaceRecord, SpaceMembershipRecord

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

    async def commit(self) -> None:
        await self._session.commit()

    @staticmethod
    def _to_domain(record: TagRecord) -> KnowledgeTag:
        return KnowledgeTag(
            id=record.id,
            space_id=record.space_id,
            name=record.name,
            color=record.color,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
