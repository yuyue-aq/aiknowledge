from __future__ import annotations

from typing import Sequence
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations import (
    ConversationKind,
    Feedback,
    FeedbackRating,
    FeedbackReviewStatus,
    MessageFeedbackContext,
)
from app.infrastructure.database.models import (
    FeedbackRecord,
    ConversationRecord,
    KnowledgeSpaceRecord,
    MessageRecord,
    SpaceMembershipRecord,
)
from app.domain.users import SpaceRole


class SqlAlchemyFeedbackRepository:
    """Persists feedback while deriving authorization context server-side."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_space_access(self, *, space_id: UUID, user_id: UUID) -> bool:
        value = await self._session.scalar(
            select(KnowledgeSpaceRecord.id).where(
                KnowledgeSpaceRecord.id == space_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
                or_(
                    KnowledgeSpaceRecord.owner_user_id == user_id,
                    exists(
                        select(SpaceMembershipRecord.space_id).where(
                            SpaceMembershipRecord.space_id == KnowledgeSpaceRecord.id,
                            SpaceMembershipRecord.user_id == user_id,
                        )
                    ),
                ),
            )
        )
        return value is not None

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
                review_status=feedback.review_status,
                corrected_answer=feedback.corrected_answer,
                review_note=feedback.review_note,
                reviewed_at=feedback.reviewed_at,
                data_usage_scope=feedback.data_usage_scope,
                pii_status=feedback.pii_status,
                created_at=feedback.created_at,
            )
        )
        await self._session.flush()

    async def list_feedback(
        self,
        space_id: UUID,
        *,
        review_status: FeedbackReviewStatus | None = None,
        rating: FeedbackRating | None = None,
        is_guest: bool | None = None,
    ) -> list[Feedback]:
        statement = (
            select(FeedbackRecord)
            .join(MessageRecord, FeedbackRecord.message_id == MessageRecord.id)
            .join(
                ConversationRecord,
                MessageRecord.conversation_id == ConversationRecord.id,
            )
            .where(ConversationRecord.space_id == space_id)
            .order_by(FeedbackRecord.created_at.desc())
        )
        if review_status is not None:
            statement = statement.where(FeedbackRecord.review_status == review_status)
        if rating is not None:
            statement = statement.where(FeedbackRecord.rating == rating)
        if is_guest is not None:
            statement = statement.where(FeedbackRecord.is_guest == is_guest)
        records = await self._session.scalars(statement)
        return [self._to_feedback(record, space_id=space_id) for record in records.all()]

    async def get_feedback(self, feedback_id: UUID) -> Feedback | None:
        record = await self._session.get(FeedbackRecord, feedback_id)
        if record is None:
            return None
        context = await self._session.scalar(
            select(ConversationRecord.space_id)
            .join(MessageRecord, MessageRecord.conversation_id == ConversationRecord.id)
            .where(MessageRecord.id == record.message_id)
        )
        if context is None:
            return None
        return self._to_feedback(record, space_id=context)

    async def update_feedback_review(self, feedback_id: UUID, **changes: object) -> Feedback | None:
        record = await self._session.get(FeedbackRecord, feedback_id, with_for_update=True)
        if record is None:
            return None
        for field, value in changes.items():
            if hasattr(record, field):
                setattr(record, field, value)
        await self._session.flush()
        return await self.get_feedback(feedback_id)

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
            review_status=record.review_status,
            corrected_answer=record.corrected_answer,
            review_note=record.review_note,
            reviewed_at=record.reviewed_at,
            data_usage_scope=record.data_usage_scope,
            pii_status=record.pii_status,
        )
