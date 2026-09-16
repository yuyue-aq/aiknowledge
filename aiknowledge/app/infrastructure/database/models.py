from __future__ import annotations

from datetime import datetime
from typing import Callable
from uuid import UUID, uuid4

from pgvector import Vector as PgVector
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.conversations import (
    ConversationKind,
    EvalScope,
    EvalRunStatus,
    FeedbackRating,
    FeedbackReason,
    MessageRole,
)
from app.domain.documents import DocumentFailureCode, DocumentStatus, DocumentVersionStatus
from app.domain.rag import AnswerStatus
from app.domain.spaces import ShareLinkStatus, SpaceVisibility


class AsyncpgVector(VECTOR):
    """Keep vectors as pgvector objects for asyncpg's binary codec.

    pgvector's generic SQLAlchemy bind processor renders a Python list as a
    text literal. That works with text-based drivers, but asyncpg's registered
    vector codec expects a ``pgvector.Vector`` value and rejects the rendered
    string. Returning the driver value only for asyncpg keeps the standard
    SQLAlchemy behavior for other PostgreSQL drivers.
    """

    cache_ok = True

    def bind_processor(self, dialect):  # type: ignore[no-untyped-def]
        if getattr(dialect, "driver", None) == "asyncpg":

            def process(value):  # type: ignore[no-untyped-def]
                if value is None or isinstance(value, PgVector):
                    return value
                return PgVector(value)

            return process
        return super().bind_processor(dialect)


def _enum_values(enum_type: type) -> list[str]:
    return [member.value for member in enum_type]  # type: ignore[attr-defined]


def _enum_column(enum_type: type, name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=_enum_values,
    )


class Base(DeclarativeBase):
    pass


class KnowledgeSpaceRecord(Base):
    __tablename__ = "knowledge_spaces"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[SpaceVisibility] = mapped_column(
        _enum_column(SpaceVisibility, "space_visibility"),
        nullable=False,
        default=SpaceVisibility.PRIVATE,
    )
    guest_feedback_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_knowledge_spaces_active", "visibility", postgresql_where=text("deleted_at IS NULL")),
    )


class CategoryRecord(Base):
    __tablename__ = "categories"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_open: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_categories_space_open", "space_id", "is_open"),
        UniqueConstraint("space_id", "name", name="uq_categories_space_name"),
    )


class ShareLinkRecord(Base):
    __tablename__ = "share_links"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[ShareLinkStatus] = mapped_column(
        _enum_column(ShareLinkStatus, "share_link_status"),
        nullable=False,
        default=ShareLinkStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_share_links_active", "space_id", "status"),)


share_link_categories = Table(
    "share_link_categories",
    Base.metadata,
    Column(
        "share_link_id",
        PG_UUID(as_uuid=True),
        ForeignKey("share_links.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "category_id",
        PG_UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class DocumentRecord(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        _enum_column(DocumentStatus, "document_status"),
        nullable=False,
        default=DocumentStatus.PROCESSING,
    )
    active_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "document_versions.id",
            name="fk_documents_active_version",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    failure_code: Mapped[DocumentFailureCode | None] = mapped_column(
        _enum_column(DocumentFailureCode, "document_failure_code"), nullable=True
    )
    failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_documents_space_status", "space_id", "status"),
        Index(
            "uq_documents_active_space_sha256",
            "space_id",
            "sha256",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class DocumentVersionRecord(Base):
    __tablename__ = "document_versions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[DocumentVersionStatus] = mapped_column(
        _enum_column(DocumentVersionStatus, "document_version_status"),
        nullable=False,
        default=DocumentVersionStatus.PROCESSING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
        Index("ix_document_versions_document_status", "document_id", "status"),
    )


class ChunkRecord(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    space_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(AsyncpgVector(1024), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal", name="uq_chunks_version_ordinal"),
        Index("ix_chunks_scope_active", "space_id", "category_id", "is_active"),
        Index(
            "ix_chunks_embedding_hnsw_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class ConversationRecord(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[ConversationKind] = mapped_column(
        _enum_column(ConversationKind, "conversation_kind"), nullable=False
    )
    share_link_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("share_links.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_conversations_space_kind", "space_id", "kind"),)


class MessageRecord(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(
        _enum_column(MessageRole, "message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    answer_status: Mapped[AnswerStatus | None] = mapped_column(
        _enum_column(AnswerStatus, "answer_status"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)


class CitationRecord(Base):
    __tablename__ = "citations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True
    )
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quoted_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (Index("ix_citations_message", "message_id"),)


class RagRunRecord(Base):
    __tablename__ = "rag_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    trace_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True
    )
    message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rewritten_question: Mapped[str] = mapped_column(Text, nullable=False)
    model_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    retrieval_config_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False
    )
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    selected_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_token_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_rag_runs_message", "message_id"),)


class FeedbackRecord(Base):
    __tablename__ = "feedback"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[FeedbackRating] = mapped_column(
        _enum_column(FeedbackRating, "feedback_rating"), nullable=False
    )
    reason: Mapped[FeedbackReason | None] = mapped_column(
        _enum_column(FeedbackReason, "feedback_reason"), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_guest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvalCaseRecord(Base):
    __tablename__ = "eval_cases"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_document_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    scope: Mapped[EvalScope] = mapped_column(
        _enum_column(EvalScope, "eval_scope"), nullable=False, default=EvalScope.OWNER
    )
    category_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvalRunRecord(Base):
    __tablename__ = "eval_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[EvalRunStatus] = mapped_column(
        _enum_column(EvalRunStatus, "eval_run_status"),
        nullable=False,
        default=EvalRunStatus.PENDING,
    )
    retrieval_config_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvalResultRecord(Base):
    __tablename__ = "eval_results"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    eval_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    eval_case_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    answer_status: Mapped[AnswerStatus] = mapped_column(
        _enum_column(AnswerStatus, "eval_answer_status"), nullable=False
    )
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reviewer_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    __table_args__ = (
        UniqueConstraint("eval_run_id", "eval_case_id", name="uq_eval_results_run_case"),
    )
