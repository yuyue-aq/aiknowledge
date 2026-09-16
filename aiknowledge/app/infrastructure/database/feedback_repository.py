from __future__ import annotations

from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations import (
    ConversationKind,
    Feedback,
    MessageFeedbackContext,
)
from app.infrastructure.database.models import (
    FeedbackRecord,
    ConversationRecord,
    KnowledgeSpaceRecord,
    MessageRecord,
)


class SqlAlchemyFeedbackRepository:
    """Persists feedback while deriving authorization context server-side."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_message_context(self, message_id: UUID) -> MessageFeedbackContext | None:
        result = await self._session.execute(
            select(
                MessageRecord.id.label("message_id"),
                ConversationRecord.space_id,
                ConversationRecord.kind,
                ConversationRecord.share_link_id,
                KnowledgeSpaceRecord.guest_feedback_enabled,
            )
            .join(
                ConversationRecord,
                MessageRecord.conversation_id == ConversationRecord.id,
            )
            .join(
                KnowledgeSpaceRecord,
                ConversationRecord.space_id == KnowledgeSpaceRecord.id,
            )
            .where(
                MessageRecord.id == message_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return MessageFeedbackContext(
            message_id=row.message_id,
            space_id=row.space_id,
            conversation_kind=ConversationKind(row.kind),
            share_link_id=row.share_link_id,
            guest_feedback_enabled=row.guest_feedback_enabled,
        )

    async def add_feedback(self, feedback: Feedback) -> None:
        self._session.add(
            FeedbackRecord(
                id=feedback.id,
                message_id=feedback.message_id,
                rating=feedback.rating,
                reason=feedback.reason,
                comment=feedback.comment,
                is_guest=feedback.is_guest,
                created_at=feedback.created_at,
            )
        )
        await self._session.flush()

    async def list_feedback(self, space_id: UUID) -> list[Feedback]:
        records = await self._session.scalars(
            select(FeedbackRecord)
            .join(MessageRecord, FeedbackRecord.message_id == MessageRecord.id)
            .join(
                ConversationRecord,
                MessageRecord.conversation_id == ConversationRecord.id,
            )
            .where(ConversationRecord.space_id == space_id)
            .order_by(FeedbackRecord.created_at.desc())
        )
        return [self._to_feedback(record, space_id=space_id) for record in records.all()]

    async def commit(self) -> None:
        await self._session.commit()

    @staticmethod
    def _to_feedback(record: FeedbackRecord, *, space_id: UUID) -> Feedback:
        return Feedback(
            id=record.id,
            message_id=record.message_id,
            space_id=space_id,
            rating=record.rating,
            reason=record.reason,
            comment=record.comment,
            is_guest=record.is_guest,
            created_at=record.created_at,
        )
