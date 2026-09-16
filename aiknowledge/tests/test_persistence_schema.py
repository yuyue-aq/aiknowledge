from __future__ import annotations

from app.infrastructure.database.models import (
    Base,
    ChunkRecord,
    DocumentRecord,
    EvalCaseRecord,
    FeedbackRecord,
    RagRunRecord,
)


def test_initial_schema_covers_spaces_documents_retrieval_and_quality_records() -> None:
    table_names = set(Base.metadata.tables)

    assert {
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
        "eval_runs",
        "eval_results",
        "rag_runs",
    } <= table_names
    # Authentication is intentionally deferred; no fake user table or owner
    # foreign key should silently give a false sense of authorization.
    assert "users" not in table_names
    assert "owner_user_id" not in Base.metadata.tables["knowledge_spaces"].c


def test_document_and_chunk_schema_preserves_safe_retrieval_invariants() -> None:
    documents = DocumentRecord.__table__
    chunks = ChunkRecord.__table__

    assert documents.c.category_id.nullable is True
    assert documents.c.active_version_id.nullable is True
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


def test_evaluation_cases_preserve_the_scope_and_public_category_snapshot() -> None:
    eval_cases = EvalCaseRecord.__table__

    assert "scope" in eval_cases.c
    assert set(eval_cases.c.scope.type.enums) == {"OWNER", "PUBLIC", "OUT_OF_SCOPE"}
    assert "category_ids" in eval_cases.c


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
