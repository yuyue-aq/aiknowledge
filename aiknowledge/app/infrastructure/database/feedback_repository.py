from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from sqlalchemy import String, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.conversations import (
    ConversationKind,
    Feedback,
    FeedbackRating,
    FeedbackReviewStatus,
    MessageFeedbackContext,
    MessageRole,
)
from app.infrastructure.database.models import (
    EvalCaseRecord,
    FeedbackRecord,
    ConversationRecord,
    KnowledgeSpaceRecord,
    MessageRecord,
    RagRunRecord,
    SpaceMembershipRecord,
    share_link_categories,
)
from app.domain.users import SpaceRole


def original_feedback_question_expression():
    """Prefer the persisted user/answer pair; support pre-link historical messages."""
    paired_user = aliased(MessageRecord)
    paired_question = (
        select(paired_user.content)
        .where(
            cast(paired_user.id, String) == RagRunRecord.model_snapshot['user_message_id'].astext,
            paired_user.conversation_id == MessageRecord.conversation_id,
            paired_user.role == MessageRole.USER,
        )
        .limit(1)
        .correlate(MessageRecord, RagRunRecord)
        .scalar_subquery()
    )
    previous_user = aliased(MessageRecord)
    previous_question = (
        select(previous_user.content)
        .where(
            previous_user.conversation_id == MessageRecord.conversation_id,
            previous_user.role == MessageRole.USER,
            previous_user.created_at <= MessageRecord.created_at,
        )
        .order_by(previous_user.created_at.desc(), previous_user.id.desc())
        .limit(1)
        .correlate(MessageRecord)
        .scalar_subquery()
    )
    return func.coalesce(
        paired_question,
        RagRunRecord.model_snapshot['query_diagnostics']['original_question'].astext,
        previous_question,
    )


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
        original_question = original_feedback_question_expression()
        statement = (
            select(
                FeedbackRecord,
                func.coalesce(original_question, RagRunRecord.rewritten_question),
                MessageRecord.content,
                EvalCaseRecord.id,
                ConversationRecord.share_link_id,
            )
            .join(MessageRecord, FeedbackRecord.message_id == MessageRecord.id)
            .outerjoin(RagRunRecord, RagRunRecord.message_id == MessageRecord.id)
            .join(
                ConversationRecord,
                MessageRecord.conversation_id == ConversationRecord.id,
            )
            .outerjoin(
                EvalCaseRecord,
                EvalCaseRecord.source_feedback_id == FeedbackRecord.id,
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
        records = await self._session.execute(statement)
        rows = records.all()
        categories_by_link = await self._category_ids_by_share_links(
            {share_link_id for _, _, _, _, share_link_id in rows if share_link_id is not None}
        )
        return [
            replace(
                self._to_feedback(record, space_id=space_id),
                question=question,
                original_answer=answer,
                eval_case_id=eval_case_id,
                source_category_ids=categories_by_link.get(share_link_id, ()),
            )
            for record, question, answer, eval_case_id, share_link_id in rows
        ]

    async def get_feedback(self, feedback_id: UUID) -> Feedback | None:
        result = await self._session.execute(
            select(
                FeedbackRecord,
                ConversationRecord.space_id,
                EvalCaseRecord.id,
                ConversationRecord.share_link_id,
            )
            .select_from(FeedbackRecord)
            .join(MessageRecord, FeedbackRecord.message_id == MessageRecord.id)
            .join(ConversationRecord, MessageRecord.conversation_id == ConversationRecord.id)
            .outerjoin(EvalCaseRecord, EvalCaseRecord.source_feedback_id == FeedbackRecord.id)
            .where(FeedbackRecord.id == feedback_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        record, space_id, eval_case_id, share_link_id = row
        categories_by_link = await self._category_ids_by_share_links(
            {share_link_id} if share_link_id is not None else set()
        )
        return replace(
            self._to_feedback(record, space_id=space_id),
            eval_case_id=eval_case_id,
            source_category_ids=categories_by_link.get(share_link_id, ()),
        )

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

    async def _category_ids_by_share_links(
        self, share_link_ids: set[UUID]
    ) -> dict[UUID, tuple[UUID, ...]]:
        if not share_link_ids:
            return {}
        result = await self._session.execute(
            select(share_link_categories.c.share_link_id, share_link_categories.c.category_id)
            .where(share_link_categories.c.share_link_id.in_(share_link_ids))
            .order_by(share_link_categories.c.category_id)
        )
        grouped: dict[UUID, list[UUID]] = {}
        for link_id, category_id in result.all():
            grouped.setdefault(link_id, []).append(category_id)
        return {link_id: tuple(category_ids) for link_id, category_ids in grouped.items()}
