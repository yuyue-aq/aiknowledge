from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations import (
    CitationSnapshot,
    Conversation,
    ConversationKind,
    ConversationMessage,
    RagRun,
    RetrievedChunk,
)
from app.domain.documents import DocumentStatus
from app.domain.spaces import PublicRetrievalScope, SpaceVisibility
from app.infrastructure.database.models import (
    CategoryRecord,
    ChunkRecord,
    CitationRecord,
    ConversationRecord,
    DocumentRecord,
    KnowledgeSpaceRecord,
    MessageRecord,
    RagRunRecord,
)


class SqlAlchemyConversationRepository:
    """Persistence adapter for conversations and scope-filtered pgvector hits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_active_space(self, space_id: UUID) -> bool:
        space_id_value = await self._session.scalar(
            select(KnowledgeSpaceRecord.id).where(
                KnowledgeSpaceRecord.id == space_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
        )
        return space_id_value is not None

    async def add_conversation(self, conversation: Conversation) -> None:
        self._session.add(
            ConversationRecord(
                id=conversation.id,
                space_id=conversation.space_id,
                kind=conversation.kind,
                share_link_id=conversation.share_link_id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
        )
        await self._session.flush()

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        record = await self._session.get(ConversationRecord, conversation_id)
        return self._to_conversation(record) if record is not None else None

    async def list_conversations(self, space_id: UUID) -> list[Conversation]:
        records = await self._session.scalars(
            select(ConversationRecord)
            .join(
                KnowledgeSpaceRecord,
                ConversationRecord.space_id == KnowledgeSpaceRecord.id,
            )
            .where(
                ConversationRecord.space_id == space_id,
                ConversationRecord.kind == ConversationKind.OWNER,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
            .order_by(ConversationRecord.updated_at.desc(), ConversationRecord.id.desc())
        )
        return [self._to_conversation(record) for record in records.all()]

    async def set_conversation_title(self, conversation_id: UUID, title: str) -> None:
        record = await self._session.get(ConversationRecord, conversation_id)
        if record is None:
            return
        record.title = title
        record.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def add_message(self, message: ConversationMessage) -> None:
        self._session.add(
            MessageRecord(
                id=message.id,
                conversation_id=message.conversation_id,
                role=message.role,
                content=message.content,
                answer_status=message.answer_status,
                model=message.model,
                prompt_tokens=message.prompt_tokens,
                completion_tokens=message.completion_tokens,
                created_at=message.created_at,
            )
        )
        await self._session.flush()

    async def add_citations(self, citations: Sequence[CitationSnapshot]) -> None:
        for citation in citations:
            self._session.add(
                CitationRecord(
                    id=citation.id,
                    message_id=citation.message_id,
                    chunk_id=citation.chunk_id,
                    document_name=citation.document_name,
                    quoted_text=citation.quoted_text,
                    page_number=citation.page_number,
                    ordinal=citation.ordinal,
                    score=citation.score,
                )
            )
        if citations:
            await self._session.flush()

    async def add_rag_run(self, run: RagRun) -> None:
        self._session.add(
            RagRunRecord(
                id=run.id,
                trace_id=run.trace_id,
                message_id=run.message_id,
                prompt_version=run.prompt_version,
                rewritten_question=run.rewritten_question,
                model_snapshot=dict(run.model_snapshot),
                retrieval_config_snapshot=dict(run.retrieval_config_snapshot),
                retrieved_chunk_ids=[str(item) for item in run.retrieved_chunk_ids],
                selected_chunk_ids=[str(item) for item in run.selected_chunk_ids],
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                first_token_latency_ms=run.first_token_latency_ms,
                total_latency_ms=run.total_latency_ms,
                estimated_cost=run.estimated_cost,
                created_at=run.created_at,
            )
        )
        await self._session.flush()

    async def list_messages(self, conversation_id: UUID) -> list[ConversationMessage]:
        records = await self._session.scalars(
            select(MessageRecord)
            .where(MessageRecord.conversation_id == conversation_id)
            .order_by(MessageRecord.created_at, MessageRecord.id)
        )
        return [self._to_message(record) for record in records.all()]

    async def list_citations(self, message_ids: Sequence[UUID]) -> list[CitationSnapshot]:
        if not message_ids:
            return []
        records = await self._session.scalars(
            select(CitationRecord)
            .where(CitationRecord.message_id.in_(message_ids))
            .order_by(CitationRecord.ordinal, CitationRecord.id)
        )
        return [self._to_citation(record) for record in records.all()]

    async def delete_conversation(self, conversation_id: UUID) -> None:
        record = await self._session.get(ConversationRecord, conversation_id)
        if record is None:
            return
        await self._session.delete(record)
        await self._session.flush()

    async def retrieve_owner(
        self, *, space_id: UUID, embedding: list[float], limit: int
    ) -> list[RetrievedChunk]:
        statement = self._base_retrieval_statement(embedding).where(
            ChunkRecord.space_id == space_id,
        )
        result = await self._session.execute(statement.limit(limit))
        return self._map_retrieval_rows(result.all())

    async def retrieve_public(
        self,
        *,
        scope: PublicRetrievalScope,
        embedding: list[float],
        limit: int,
    ) -> list[RetrievedChunk]:
        # An inner category join intentionally excludes unclassified data.
        # The remaining predicates execute in the same SQL statement as the
        # vector ordering; forbidden rows never become model context.
        statement = (
            self._base_retrieval_statement(embedding)
            .join(CategoryRecord, ChunkRecord.category_id == CategoryRecord.id)
            .where(
                ChunkRecord.space_id == scope.space_id,
                ChunkRecord.category_id.in_(scope.category_ids),
                CategoryRecord.space_id == scope.space_id,
                CategoryRecord.is_open.is_(True),
                CategoryRecord.deleted_at.is_(None),
                KnowledgeSpaceRecord.visibility == SpaceVisibility.PUBLIC,
            )
        )
        result = await self._session.execute(statement.limit(limit))
        return self._map_retrieval_rows(result.all())

    async def commit(self) -> None:
        await self._session.commit()

    @staticmethod
    def _base_retrieval_statement(embedding: list[float]) -> Select:
        distance = ChunkRecord.embedding.cosine_distance(embedding).label("distance")
        return (
            select(
                ChunkRecord.id,
                ChunkRecord.document_id,
                DocumentRecord.original_filename.label("document_name"),
                ChunkRecord.content,
                ChunkRecord.page_number,
                ChunkRecord.ordinal,
                distance,
            )
            .join(DocumentRecord, ChunkRecord.document_id == DocumentRecord.id)
            .join(
                KnowledgeSpaceRecord,
                ChunkRecord.space_id == KnowledgeSpaceRecord.id,
            )
            .where(
                ChunkRecord.is_active.is_(True),
                DocumentRecord.status == DocumentStatus.READY,
                DocumentRecord.deleted_at.is_(None),
                DocumentRecord.active_version_id == ChunkRecord.document_version_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
            .order_by(distance)
        )

    @staticmethod
    def _map_retrieval_rows(rows: Sequence[object]) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                id=row.id,  # type: ignore[attr-defined]
                document_id=row.document_id,  # type: ignore[attr-defined]
                document_name=row.document_name,  # type: ignore[attr-defined]
                content=row.content,  # type: ignore[attr-defined]
                page_number=row.page_number,  # type: ignore[attr-defined]
                ordinal=row.ordinal,  # type: ignore[attr-defined]
                # pgvector cosine distance is 1 - cosine similarity.
                score=1 - float(row.distance),  # type: ignore[attr-defined]
            )
            for row in rows
        ]

    @staticmethod
    def _to_conversation(record: ConversationRecord) -> Conversation:
        return Conversation(
            id=record.id,
            space_id=record.space_id,
            kind=ConversationKind(record.kind),
            share_link_id=record.share_link_id,
            title=record.title,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_message(record: MessageRecord) -> ConversationMessage:
        return ConversationMessage(
            id=record.id,
            conversation_id=record.conversation_id,
            role=record.role,
            content=record.content,
            answer_status=record.answer_status,
            model=record.model,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            created_at=record.created_at,
        )

    @staticmethod
    def _to_citation(record: CitationRecord) -> CitationSnapshot:
        return CitationSnapshot(
            id=record.id,
            message_id=record.message_id,
            chunk_id=record.chunk_id,
            document_name=record.document_name,
            quoted_text=record.quoted_text,
            page_number=record.page_number,
            ordinal=record.ordinal,
            score=record.score,
        )
