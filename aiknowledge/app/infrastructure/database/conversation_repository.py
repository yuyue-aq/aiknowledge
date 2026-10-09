from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import replace
from typing import Sequence
from uuid import UUID

from sqlalchemy import Select, exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from app.services.section_context import page_heading

from app.domain.conversations import (
    CitationSnapshot,
    Conversation,
    ConversationKind,
    ConversationMessage,
    RagRun,
    RetrievedChunk,
)
from app.domain.documents import DocumentStatus
from app.domain.public_answers import PublicContentMode
from app.domain.retrieval import RetrievalMetadataFilter
from app.domain.spaces import PublicRetrievalScope, SpaceVisibility, ShareLinkStatus
from app.infrastructure.database.models import (
    CategoryRecord,
    ChunkRecord,
    CitationRecord,
    ConversationRecord,
    DocumentRecord,
    KnowledgeSpaceRecord,
    MessageRecord,
    RagRunRecord,
    SpaceMembershipRecord,
    ShareLinkRecord,
    PublicAnswerVersionRecord,
    PublicAnswerSourceRecord,
    TagRecord,
    DocumentVersionRecord,
    document_tags,
    share_link_categories,
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

    async def has_space_access(self, *, space_id: UUID, user_id: UUID) -> bool:
        space = await self._session.scalar(
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
        return space is not None

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
                    public_answer_version_id=citation.public_answer_version_id,
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
        available_document = exists(self._base_retrieval_statement(None).where(ChunkRecord.id == CitationRecord.chunk_id).order_by(None))
        available_public_answer = exists(select(PublicAnswerVersionRecord.id).where(
            PublicAnswerVersionRecord.id == CitationRecord.public_answer_version_id,
            PublicAnswerVersionRecord.status == 'PUBLISHED',
        ))
        records = await self._session.execute(
            select(CitationRecord, or_(available_document, available_public_answer).label('source_available'))
            .where(CitationRecord.message_id.in_(message_ids))
            .order_by(CitationRecord.ordinal, CitationRecord.id)
        )
        return [replace(self._to_citation(record), source_available=bool(current)) for record, current in records.all()]

    async def list_query_diagnostics(self, message_ids: Sequence[UUID]) -> dict[UUID, dict[str, object]]:
        if not message_ids:
            return {}
        records = await self._session.scalars(
            select(RagRunRecord).where(RagRunRecord.message_id.in_(message_ids))
        )
        diagnostics = {}
        for record in records.all():
            value = record.model_snapshot.get('query_diagnostics')
            if isinstance(value, dict):
                diagnostics[record.message_id] = value
        return diagnostics

    async def delete_conversation(self, conversation_id: UUID) -> None:
        record = await self._session.get(ConversationRecord, conversation_id)
        if record is None:
            return
        await self._session.delete(record)
        await self._session.flush()

    async def retrieve_owner(
        self, *, space_id: UUID, embedding: list[float], limit: int,
        metadata_filter: RetrievalMetadataFilter | None = None,
    ) -> list[RetrievedChunk]:
        statement = self._base_retrieval_statement(embedding).where(
            ChunkRecord.space_id == space_id,
        )
        statement = self._apply_metadata_filter(statement, metadata_filter or RetrievalMetadataFilter())
        result = await self._session.execute(statement.limit(limit))
        return self._map_retrieval_rows(result.all())

    async def retrieve_public(
        self,
        *,
        scope: PublicRetrievalScope,
        embedding: list[float],
        limit: int,
        metadata_filter: RetrievalMetadataFilter | None = None,
    ) -> list[RetrievedChunk]:
        if scope.content_mode is PublicContentMode.PUBLISHED_ANSWERS:
            statement = self._public_answer_statement(
                scope=scope, embedding=embedding, metadata_filter=metadata_filter
            )
            result = await self._session.execute(statement.limit(limit))
            return self._map_retrieval_rows(result.all())
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
        statement = self._apply_metadata_filter(statement, metadata_filter or RetrievalMetadataFilter())
        result = await self._session.execute(statement.limit(limit))
        return self._map_retrieval_rows(result.all())

    async def list_public_faq_questions(
        self, *, scope: PublicRetrievalScope, limit: int = 6
    ) -> list[str]:
        if scope.content_mode is not PublicContentMode.PUBLISHED_ANSWERS or limit <= 0:
            return []
        bounded_limit = min(limit, 6)
        statement = self._public_answer_statement(scope=scope, embedding=None).with_only_columns(
            PublicAnswerVersionRecord.question.label('question'), maintain_column_froms=True
        ).order_by(None).order_by(
            PublicAnswerVersionRecord.published_at.desc(), PublicAnswerVersionRecord.id
        ).limit(bounded_limit)
        rows = (await self._session.execute(statement)).all()
        return [row.question for row in rows]

    async def keyword_corpus(self,*,space_id: UUID,public_scope: PublicRetrievalScope | None,limit: int,
        metadata_filter: RetrievalMetadataFilter | None = None):
        if public_scope is not None and public_scope.content_mode is PublicContentMode.PUBLISHED_ANSWERS:
            if public_scope.space_id != space_id:
                return []
            statement = self._public_answer_statement(
                scope=public_scope, embedding=None, metadata_filter=metadata_filter
            ).order_by(PublicAnswerVersionRecord.id)
            result = await self._session.execute(statement.limit(limit))
            return self._map_retrieval_rows(result.all())
        statement=self._base_retrieval_statement(None).where(ChunkRecord.space_id==space_id).order_by(None).order_by(ChunkRecord.id)
        if public_scope is not None:
            if public_scope.space_id!=space_id:return []
            statement=statement.join(CategoryRecord,ChunkRecord.category_id==CategoryRecord.id).where(
                ChunkRecord.category_id.in_(public_scope.category_ids),CategoryRecord.space_id==space_id,
                CategoryRecord.is_open.is_(True),CategoryRecord.deleted_at.is_(None),
                KnowledgeSpaceRecord.visibility==SpaceVisibility.PUBLIC)
        statement=self._apply_metadata_filter(statement,metadata_filter or RetrievalMetadataFilter())
        result=await self._session.execute(statement.limit(limit))
        return self._map_retrieval_rows(result.all())

    async def commit(self) -> None:
        await self._session.commit()

    @staticmethod
    def _base_retrieval_statement(embedding: list[float] | None) -> Select:
        page_start = aliased(ChunkRecord, name='page_start')
        # Read only the same live document/version/page/category. In public
        # retrieval this cannot cross the category authorization boundary.
        page_prefix = select(page_start.content).where(
            page_start.document_id == ChunkRecord.document_id,
            page_start.document_version_id == ChunkRecord.document_version_id,
            page_start.page_number == ChunkRecord.page_number,
            page_start.category_id.is_not_distinct_from(ChunkRecord.category_id),
            page_start.is_active.is_(True), ChunkRecord.page_number.is_not(None),
        ).order_by(page_start.ordinal).limit(1).correlate(ChunkRecord).scalar_subquery()
        distance = (ChunkRecord.embedding.cosine_distance(embedding) if embedding is not None else literal(1.)).label('distance')
        return (
            select(
                ChunkRecord.id,
                ChunkRecord.document_id,
                DocumentRecord.original_filename.label("document_name"),
                ChunkRecord.content,
                ChunkRecord.page_number,
                ChunkRecord.ordinal,
                ChunkRecord.document_version_id,
                ChunkRecord.source_block_id,
                ChunkRecord.char_start,
                ChunkRecord.char_end,
                ChunkRecord.content_hash,
                ChunkRecord.token_count,
                ChunkRecord.heading_path,
                page_prefix.label('page_prefix'),
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
                DocumentRecord.is_enabled.is_(True),
                or_(DocumentRecord.effective_at.is_(None), DocumentRecord.effective_at <= func.clock_timestamp()),
                or_(DocumentRecord.expires_at.is_(None), DocumentRecord.expires_at > func.clock_timestamp()),
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
            .order_by(distance, ChunkRecord.id)
        )

    async def generation_scope_snapshot(self, *, space_id: UUID, user_id: UUID | None, public_scope: PublicRetrievalScope | None):
        statement = select(KnowledgeSpaceRecord.access_revision, KnowledgeSpaceRecord.knowledge_revision).where(
            KnowledgeSpaceRecord.id == space_id, KnowledgeSpaceRecord.deleted_at.is_(None))
        if public_scope is not None:
            statement = statement.where(KnowledgeSpaceRecord.visibility == SpaceVisibility.PUBLIC)
            if public_scope.share_link_id.int != 0:
                statement = statement.where(exists(select(ShareLinkRecord.id).where(
                    ShareLinkRecord.id == public_scope.share_link_id, ShareLinkRecord.space_id == space_id,
                    ShareLinkRecord.status == ShareLinkStatus.ACTIVE,
                    ShareLinkRecord.content_mode == public_scope.content_mode.value,
                    or_(ShareLinkRecord.expires_at.is_(None), ShareLinkRecord.expires_at > func.clock_timestamp()),
                )))
            categories = select(CategoryRecord.id).where(CategoryRecord.space_id == space_id,
                CategoryRecord.deleted_at.is_(None), CategoryRecord.is_open.is_(True), CategoryRecord.id.in_(public_scope.category_ids))
            if public_scope.share_link_id.int != 0:
                categories = categories.join(share_link_categories, share_link_categories.c.category_id == CategoryRecord.id).where(
                    share_link_categories.c.share_link_id == public_scope.share_link_id)
            actual = await self._session.scalars(categories)
            if set(actual.all()) != set(public_scope.category_ids) or not public_scope.category_ids:
                return None
        elif user_id is not None:
            statement = statement.where(or_(KnowledgeSpaceRecord.owner_user_id == user_id,
                exists(select(SpaceMembershipRecord.space_id).where(SpaceMembershipRecord.space_id == space_id,
                    SpaceMembershipRecord.user_id == user_id))))
        row = (await self._session.execute(statement)).first()
        return tuple(row) if row is not None else None

    async def validate_generation_chunks(self, *, space_id: UUID, public_scope: PublicRetrievalScope | None,
        chunk_ids: tuple[UUID, ...], metadata_filter: RetrievalMetadataFilter | None = None) -> bool:
        if not chunk_ids:
            return True
        if public_scope is not None and public_scope.content_mode is PublicContentMode.PUBLISHED_ANSWERS:
            result = await self._session.execute(self._public_answer_statement(
                scope=public_scope, embedding=None, metadata_filter=metadata_filter,
            ).where(PublicAnswerVersionRecord.id.in_(chunk_ids)).order_by(None))
            return {row.id for row in result.all()} == set(chunk_ids)
        statement = self._base_retrieval_statement(None).where(ChunkRecord.space_id == space_id, ChunkRecord.id.in_(chunk_ids)).order_by(None)
        if public_scope is not None:
            statement = statement.join(CategoryRecord, CategoryRecord.id == ChunkRecord.category_id).where(
                ChunkRecord.category_id.in_(public_scope.category_ids), CategoryRecord.is_open.is_(True),
                CategoryRecord.deleted_at.is_(None), CategoryRecord.space_id == space_id)
        statement = self._apply_metadata_filter(statement, metadata_filter or RetrievalMetadataFilter())
        rows = (await self._session.execute(statement)).all()
        return {row.id for row in rows} == set(chunk_ids)

    @staticmethod
    def _public_answer_statement(*, scope, embedding, metadata_filter=None):
        """Build guest-safe retrieval rows from immutable published snapshots."""
        metadata_filter = metadata_filter or RetrievalMetadataFilter()
        allowed_category_ids = set(scope.category_ids)
        if metadata_filter.category_ids:
            allowed_category_ids &= set(metadata_filter.category_ids)
        distance = (
            PublicAnswerVersionRecord.embedding.cosine_distance(embedding)
            if embedding is not None else literal(1.0)
        ).label('distance')
        valid_source_count = (
            select(func.count(PublicAnswerSourceRecord.document_id))
            .select_from(PublicAnswerSourceRecord)
            .join(DocumentRecord, DocumentRecord.id == PublicAnswerSourceRecord.document_id)
            .where(
                PublicAnswerSourceRecord.answer_version_id == PublicAnswerVersionRecord.id,
                PublicAnswerSourceRecord.document_version_id == DocumentRecord.active_version_id,
                DocumentRecord.status == DocumentStatus.READY,
                DocumentRecord.is_enabled.is_(True),
                DocumentRecord.deleted_at.is_(None),
                or_(DocumentRecord.effective_at.is_(None), DocumentRecord.effective_at <= func.clock_timestamp()),
                or_(DocumentRecord.expires_at.is_(None), DocumentRecord.expires_at > func.clock_timestamp()),
            )
            .correlate(PublicAnswerVersionRecord)
            .scalar_subquery()
        )
        content = (
            literal('问题：') + PublicAnswerVersionRecord.question
            + literal('\n答案：') + PublicAnswerVersionRecord.answer
        )
        return (
            select(
                PublicAnswerVersionRecord.id.label('id'),
                PublicAnswerVersionRecord.answer_id.label('document_id'),
                PublicAnswerVersionRecord.question.label('document_name'),
                content.label('content'),
                literal(None).label('page_number'),
                PublicAnswerVersionRecord.version_number.label('ordinal'),
                PublicAnswerVersionRecord.id.label('document_version_id'),
                literal(None).label('source_block_id'),
                literal(None).label('char_start'),
                literal(None).label('char_end'),
                PublicAnswerVersionRecord.content_hash.label('content_hash'),
                literal(None).label('token_count'),
                literal(None).label('heading_path'),
                literal(None).label('page_prefix'),
                distance,
                PublicAnswerVersionRecord.id.label('public_answer_version_id'),
                PublicAnswerVersionRecord.question.label('public_answer_title'),
                PublicAnswerVersionRecord.answer.label('public_answer_text'),
                literal('PUBLISHED_ANSWER').label('source_type'),
            )
            .select_from(PublicAnswerVersionRecord)
            .join(CategoryRecord, CategoryRecord.id == PublicAnswerVersionRecord.category_id)
            .join(KnowledgeSpaceRecord, KnowledgeSpaceRecord.id == PublicAnswerVersionRecord.space_id)
            .where(
                PublicAnswerVersionRecord.space_id == scope.space_id,
                PublicAnswerVersionRecord.category_id.in_(tuple(allowed_category_ids)),
                PublicAnswerVersionRecord.status == 'PUBLISHED',
                PublicAnswerVersionRecord.source_count == valid_source_count,
                CategoryRecord.space_id == scope.space_id,
                CategoryRecord.is_open.is_(True),
                CategoryRecord.deleted_at.is_(None),
                KnowledgeSpaceRecord.visibility == SpaceVisibility.PUBLIC,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
            .order_by(distance, PublicAnswerVersionRecord.id)
        )

    @staticmethod
    def _apply_metadata_filter(statement, metadata_filter: RetrievalMetadataFilter):
        if metadata_filter.category_ids:
            category_exists = exists(select(CategoryRecord.id).where(
                CategoryRecord.id == ChunkRecord.category_id,
                CategoryRecord.space_id == ChunkRecord.space_id,
                CategoryRecord.deleted_at.is_(None),
            ))
            statement = statement.where(ChunkRecord.category_id.in_(metadata_filter.category_ids), category_exists)

        if metadata_filter.tag_ids:
            tag_match = exists(select(document_tags.c.document_id).join(
                TagRecord, TagRecord.id == document_tags.c.tag_id,
            ).where(
                document_tags.c.document_id == ChunkRecord.document_id,
                TagRecord.space_id == ChunkRecord.space_id,
                document_tags.c.tag_id.in_(metadata_filter.tag_ids),
            ))
            statement = statement.where(tag_match)

        if metadata_filter.formats:
            extensions = {
                "pdf": ("pdf",), "docx": ("docx",),
                "markdown": ("md", "markdown"), "text": ("txt",),
                "table": ("csv", "tsv", "xlsx"), "presentation": ("pptx",),
            }
            suffixes = [f"%.{suffix}" for kind in metadata_filter.formats for suffix in extensions[kind]]
            statement = statement.where(or_(*(func.lower(DocumentRecord.original_filename).like(suffix) for suffix in suffixes)))

        if metadata_filter.version_min is not None or metadata_filter.version_max is not None:
            version = select(DocumentVersionRecord.id).where(
                DocumentVersionRecord.id == DocumentRecord.active_version_id,
            )
            if metadata_filter.version_min is not None:
                version = version.where(DocumentVersionRecord.version_number >= metadata_filter.version_min)
            if metadata_filter.version_max is not None:
                version = version.where(DocumentVersionRecord.version_number <= metadata_filter.version_max)
            statement = statement.where(exists(version))

        if metadata_filter.valid_to is not None:
            statement = statement.where(or_(
                DocumentRecord.effective_at.is_(None),
                DocumentRecord.effective_at <= metadata_filter.valid_to,
            ))
        if metadata_filter.valid_from is not None:
            statement = statement.where(or_(
                DocumentRecord.expires_at.is_(None),
                DocumentRecord.expires_at > metadata_filter.valid_from,
            ))
        return statement

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
                document_version_id=getattr(row, 'document_version_id', None),
                source_block_id=getattr(row, 'source_block_id', None),
                char_start=getattr(row, 'char_start', None),
                char_end=getattr(row, 'char_end', None),
                content_hash=getattr(row, 'content_hash', None),
                token_count=getattr(row, 'token_count', None),
                heading_path=tuple(getattr(row, 'heading_path', None) or page_heading(getattr(row, 'page_prefix', None))),
                source_type=getattr(row, 'source_type', 'DOCUMENT'),
                public_answer_version_id=getattr(row, 'public_answer_version_id', None),
                public_answer_title=getattr(row, 'public_answer_title', None),
                public_answer_text=getattr(row, 'public_answer_text', None),
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
            public_answer_version_id=record.public_answer_version_id,
        )
