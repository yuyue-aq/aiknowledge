from __future__ import annotations

from app.infrastructure.database.models import (
    Base,
    ChunkRecord,
    DocumentRecord,
    EvalCaseRecord,
    FeedbackRecord,
    RagRunRecord,
    PublicAccessEventRecord,
    PublicQuestionLogRecord,
    KnowledgeSourceRecord,
)


def test_initial_schema_covers_spaces_documents_retrieval_and_quality_records() -> None:
    table_names = set(Base.metadata.tables)

    assert {
        "users",
        "refresh_tokens",
        "space_memberships",
        "knowledge_spaces",
        "categories",
        "share_links",
        "share_link_categories",
        "documents",
        "document_versions",
        "chunks",
        "conversations",
        "messages",
        "citations",
        "feedback",
        "eval_cases",
        "eval_set_versions",
        "eval_runs",
        "eval_results",
        "rag_runs",
        "knowledge_tags",
        "document_tags",
        "public_access_events",
        "knowledge_sources",
    } <= table_names
    assert "owner_user_id" in Base.metadata.tables["knowledge_spaces"].c
    assert Base.metadata.tables["knowledge_spaces"].c.owner_user_id.nullable is True
    assert Base.metadata.tables["knowledge_spaces"].c.plan.server_default is not None


def test_document_and_chunk_schema_preserves_safe_retrieval_invariants() -> None:
    documents = DocumentRecord.__table__
    chunks = ChunkRecord.__table__

    assert documents.c.category_id.nullable is True
    assert documents.c.active_version_id.nullable is True
    assert documents.c.is_enabled.server_default is not None
    assert documents.c.effective_at.nullable is True
    assert documents.c.expires_at.nullable is True
    assert documents.c.owner_user_id.nullable is True
    assert any(
        foreign_key.target_fullname == "users.id"
        for foreign_key in documents.c.owner_user_id.foreign_keys
    )
    assert any(
        foreign_key.target_fullname == "document_versions.id"
        for foreign_key in documents.c.active_version_id.foreign_keys
    )
    assert chunks.c.category_id.nullable is True
    assert chunks.c.embedding.type.dim == 1024
    assert str(chunks.c.embedding.type) == "VECTOR(1024)"
    assert any(
        index.name == "ix_chunks_embedding_hnsw_cosine"
        and index.dialect_options["postgresql"].get("using") == "hnsw"
        and index.dialect_options["postgresql"].get("ops")
        == {"embedding": "vector_cosine_ops"}
        for index in chunks.indexes
    )


def test_share_links_use_a_category_join_table_and_never_store_raw_tokens() -> None:
    share_links = Base.metadata.tables["share_links"]
    link_categories = Base.metadata.tables["share_link_categories"]

    assert "token_hash" in share_links.c
    assert "token" not in share_links.c
    assert "allowed_origins" in share_links.c
    assert set(link_categories.primary_key.columns.keys()) == {
        "share_link_id",
        "category_id",
    }


def test_feedback_schema_records_a_structured_reason_for_correction_requests() -> None:
    feedback = FeedbackRecord.__table__

    assert "reason" in feedback.c
    assert "NEEDS_CORRECTION" in feedback.c.rating.type.enums
    assert set(feedback.c.reason.type.enums) >= {
        "OFF_TOPIC",
        "SOURCE_MISMATCH",
        "OUTDATED",
        "INCOMPLETE",
        "MISSING_MATERIAL",
    }
    assert set(feedback.c.review_status.type.enums) == {"PENDING", "FIXED", "DEFERRED"}
    assert {"corrected_answer", "review_note", "reviewed_at", "data_usage_scope", "pii_status"} <= set(feedback.c.keys())


def test_evaluation_cases_preserve_the_scope_and_public_category_snapshot() -> None:
    eval_cases = EvalCaseRecord.__table__

    assert "scope" in eval_cases.c
    assert set(eval_cases.c.scope.type.enums) == {"OWNER", "PUBLIC", "OUT_OF_SCOPE"}
    assert "category_ids" in eval_cases.c


def test_evaluation_results_retain_history_when_a_live_case_changes() -> None:
    eval_results = Base.metadata.tables["eval_results"]
    foreign_key = next(
        key for key in eval_results.c.eval_case_id.foreign_keys
        if key.target_fullname == "eval_cases.id"
    )
    assert foreign_key.ondelete == "RESTRICT"
    assert "model_grade_suggestions" in eval_results.c
    assert eval_results.c.model_grade_suggestions.nullable is False


def test_rag_runs_capture_reproducible_model_and_retrieval_snapshots() -> None:
    table = RagRunRecord.__table__
    assert {
        "trace_id",
        "message_id",
        "prompt_version",
        "rewritten_question",
        "model_snapshot",
        "retrieval_config_snapshot",
        "retrieved_chunk_ids",
        "selected_chunk_ids",
        "input_tokens",
        "output_tokens",
        "first_token_latency_ms",
        "total_latency_ms",
        "estimated_cost",
    } <= set(table.c.keys())


def test_public_analytics_schema_keeps_anonymous_events_and_moderation_state() -> None:
    event = PublicAccessEventRecord.__table__
    question = PublicQuestionLogRecord.__table__
    assert {"space_id", "share_link_id", "visitor_id", "event_type", "origin", "created_at"} <= set(event.c.keys())
    assert {"is_hidden", "moderation_note", "moderated_at"} <= set(question.c.keys())


def test_knowledge_sources_schema_keeps_sync_state_and_scoped_uniqueness() -> None:
    sources = KnowledgeSourceRecord.__table__
    assert {"space_id", "kind", "locator", "status", "last_checksum", "last_synced_at", "last_error"} <= set(sources.c.keys())
    assert sources.c.locator.type.length == 2000
    assert any(
        constraint.name == "uq_knowledge_sources_space_locator"
        for constraint in sources.constraints
    )
    assert any(index.name == "ix_knowledge_sources_space_status" for index in sources.indexes)
