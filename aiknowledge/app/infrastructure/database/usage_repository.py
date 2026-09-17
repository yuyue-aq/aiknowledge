from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations import MessageRole
from app.domain.spaces import SpacePlan
from app.domain.users import SpaceRole
from app.infrastructure.database.models import (
    ConversationRecord,
    DocumentRecord,
    KnowledgeSpaceRecord,
    MessageRecord,
    SpaceMembershipRecord,
)


class SqlAlchemyUsageRepository:
    """Read-only usage counters used by plan entitlements and the dashboard."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_space_plan(self, space_id: UUID) -> SpacePlan | None:
        return await self._session.scalar(
            select(KnowledgeSpaceRecord.plan).where(
                KnowledgeSpaceRecord.id == space_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
        )

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

    async def count_documents(self, space_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.count(DocumentRecord.id)).where(
                DocumentRecord.space_id == space_id,
                DocumentRecord.deleted_at.is_(None),
            )
        )
        return int(value or 0)

    async def count_members(self, space_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.count(SpaceMembershipRecord.user_id)).where(
                SpaceMembershipRecord.space_id == space_id,
            )
        )
        return int(value or 0)

    async def count_questions(self, *, space_id: UUID, since: datetime) -> int:
        value = await self._session.scalar(
            select(func.count(MessageRecord.id))
            .join(ConversationRecord, MessageRecord.conversation_id == ConversationRecord.id)
            .where(
                ConversationRecord.space_id == space_id,
                MessageRecord.role == MessageRole.USER,
                MessageRecord.created_at >= since,
            )
        )
        return int(value or 0)
