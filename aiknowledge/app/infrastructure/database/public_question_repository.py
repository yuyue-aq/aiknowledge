from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.spaces import (
    PublicAccessEvent,
    PublicAccessEventType,
    PublicQuestionRecord,
)
from app.domain.conversations import ConversationKind, RagRun
from app.domain.rag import AnswerStatus
from app.domain.users import SpaceRole
from app.infrastructure.database.models import (
    KnowledgeSpaceRecord,
    PublicAccessEventRecord,
    PublicQuestionLogRecord,
    ConversationRecord,
    MessageRecord,
    RagRunRecord,
    ShareLinkRecord,
    SpaceMembershipRecord,
)


class SqlAlchemyPublicQuestionLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_questions(self, *, share_link_id: UUID, visitor_id: str) -> int:
        count = await self._session.scalar(
            select(func.count(PublicQuestionLogRecord.id)).where(
                PublicQuestionLogRecord.share_link_id == share_link_id,
                PublicQuestionLogRecord.visitor_id == visitor_id,
            )
        )
        return int(count or 0)

    async def add_question(
        self,
        *,
        log_id: UUID,
        share_link_id: UUID,
        visitor_id: str,
        conversation_id: UUID | None,
        question_hash: str,
        created_at: datetime,
    ) -> None:
        await self._session.execute(
            insert(PublicQuestionLogRecord).values(
                id=log_id,
                share_link_id=share_link_id,
                visitor_id=visitor_id,
                conversation_id=conversation_id,
                question_hash=question_hash,
                created_at=created_at,
            )
        )
        await self._session.flush()

    async def add_event(self, event: PublicAccessEvent) -> None:
        self._session.add(
            PublicAccessEventRecord(
                id=event.id,
                space_id=event.space_id,
                share_link_id=event.share_link_id,
                visitor_id=event.visitor_id,
                event_type=event.event_type.value,
                origin=event.origin,
                user_agent=event.user_agent,
                created_at=event.created_at,
            )
        )
        await self._session.flush()

    async def event_targets_exist(self, *, space_id: UUID, share_link_id: UUID) -> bool:
        link_id = await self._session.scalar(
            select(ShareLinkRecord.id)
            .join(KnowledgeSpaceRecord, KnowledgeSpaceRecord.id == ShareLinkRecord.space_id)
            .where(
                ShareLinkRecord.id == share_link_id,
                ShareLinkRecord.space_id == space_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
            .limit(1)
        )
        return link_id is not None

    async def list_events(self, *, space_id: UUID, since: datetime) -> list[PublicAccessEvent]:
        result = await self._session.scalars(
            select(PublicAccessEventRecord)
            .where(
                PublicAccessEventRecord.space_id == space_id,
                PublicAccessEventRecord.created_at >= since,
            )
            .order_by(PublicAccessEventRecord.created_at)
        )
        return [
            PublicAccessEvent(
                id=record.id,
                space_id=record.space_id,
                share_link_id=record.share_link_id,
                visitor_id=record.visitor_id,
                event_type=PublicAccessEventType(record.event_type),
                origin=record.origin,
                user_agent=record.user_agent,
                created_at=record.created_at,
            )
            for record in result.all()
        ]

    async def list_public_call_stats(
        self, *, space_id: UUID, since: datetime
    ) -> list[tuple[RagRun, AnswerStatus | None]]:
        rows = await self._session.execute(
            select(RagRunRecord, MessageRecord.answer_status)
            .join(MessageRecord, MessageRecord.id == RagRunRecord.message_id)
            .join(ConversationRecord, ConversationRecord.id == MessageRecord.conversation_id)
            .where(
                ConversationRecord.space_id == space_id,
                ConversationRecord.kind == ConversationKind.PUBLIC,
                RagRunRecord.created_at >= since,
            )
            .order_by(RagRunRecord.created_at)
        )
        return [
            (
                RagRun(
                    id=record.id,
                    trace_id=record.trace_id,
                    message_id=record.message_id,
                    prompt_version=record.prompt_version,
                    rewritten_question=record.rewritten_question,
                    model_snapshot=dict(record.model_snapshot),
                    retrieval_config_snapshot=dict(record.retrieval_config_snapshot),
                    retrieved_chunk_ids=tuple(UUID(value) for value in record.retrieved_chunk_ids),
                    selected_chunk_ids=tuple(UUID(value) for value in record.selected_chunk_ids),
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    first_token_latency_ms=record.first_token_latency_ms,
                    total_latency_ms=record.total_latency_ms,
                    estimated_cost=record.estimated_cost,
                    created_at=record.created_at,
                ),
                status,
            )
            for record, status in rows.all()
        ]

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

    async def list_questions(
        self, *, space_id: UUID, limit: int, offset: int
    ) -> list[PublicQuestionRecord]:
        result = await self._session.execute(
            select(PublicQuestionLogRecord)
            .join(ShareLinkRecord, ShareLinkRecord.id == PublicQuestionLogRecord.share_link_id)
            .where(ShareLinkRecord.space_id == space_id)
            .order_by(PublicQuestionLogRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [
            PublicQuestionRecord(
                id=record.id,
                share_link_id=record.share_link_id,
                visitor_id=record.visitor_id,
                conversation_id=record.conversation_id,
                question_hash=record.question_hash,
                created_at=record.created_at,
                is_hidden=record.is_hidden,
                moderation_note=record.moderation_note,
                moderated_at=record.moderated_at,
                space_id=space_id,
            )
            for record in result.scalars().all()
        ]

    async def get_question(self, question_id: UUID) -> PublicQuestionRecord | None:
        row = await self._session.execute(
            select(PublicQuestionLogRecord, ShareLinkRecord.space_id).join(
                ShareLinkRecord, ShareLinkRecord.id == PublicQuestionLogRecord.share_link_id
            ).where(PublicQuestionLogRecord.id == question_id)
        )
        result = row.first()
        if result is None:
            return None
        record, space_id = result
        return PublicQuestionRecord(
            id=record.id,
            share_link_id=record.share_link_id,
            visitor_id=record.visitor_id,
            conversation_id=record.conversation_id,
            question_hash=record.question_hash,
            created_at=record.created_at,
            is_hidden=record.is_hidden,
            moderation_note=record.moderation_note,
            moderated_at=record.moderated_at,
            space_id=space_id,
        )

    async def update_question(self, record: PublicQuestionRecord) -> None:
        row = await self._session.get(PublicQuestionLogRecord, record.id)
        if row is None:
            return
        row.is_hidden = record.is_hidden
        row.moderation_note = record.moderation_note
        row.moderated_at = record.moderated_at
        await self._session.flush()
