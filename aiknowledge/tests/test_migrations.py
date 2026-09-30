from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_alembic_has_one_linear_schema_head_and_preserves_initial_revision() -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert script.get_current_head() == "20260929_0016"
    revision = script.get_revision("20260911_0001")
    assert revision is not None
    assert revision.down_revision is None


def test_latest_migration_accepts_all_document_failure_codes() -> None:
    from io import StringIO
    from alembic import command
    from app.domain.documents import DocumentFailureCode

    output = StringIO()
    config = Config(str(PROJECT_ROOT / "alembic.ini"), output_buffer=output)
    command.upgrade(config, "20260917_0015:head", sql=True)
    sql = output.getvalue()
    for code in DocumentFailureCode:
        assert f"'{code.value}'" in sql
    assert "DROP CONSTRAINT document_failure_code" in sql
    assert "ADD CONSTRAINT document_failure_code CHECK" in sql


def test_initial_migration_enables_pgvector_without_dropping_shared_extension() -> None:
    migration = (
        PROJECT_ROOT / "migrations" / "versions" / "20260911_0001_initial_schema.py"
    ).read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert "DROP EXTENSION" not in migration


def test_answer_status_migration_matches_domain_terminal_states() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260916_0003_answer_statuses.py"
    ).read_text(encoding="utf-8")

    for status in ("ANSWERED", "INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE", "CONFLICT", "FAILED"):
        assert f"'{status}'" in migration


def test_auth_migration_adds_users_refresh_tokens_and_memberships() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260917_0004_auth_memberships.py"
    ).read_text(encoding="utf-8")

    for table in ("users", "refresh_tokens", "space_memberships"):
        assert f'"{table}"' in migration
    assert "owner_user_id" in migration


def test_document_availability_migration_adds_retrieval_window() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260917_0006_document_availability.py"
    ).read_text(encoding="utf-8")
    assert "is_enabled" in migration
    assert "effective_at" in migration
    assert "expires_at" in migration


def test_feedback_review_migration_adds_review_and_governance_fields() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260917_0007_feedback_review.py"
    ).read_text(encoding="utf-8")
    assert "review_status" in migration
    assert "corrected_answer" in migration
    assert "data_usage_scope" in migration
    assert "pii_status" in migration


def test_knowledge_tags_migration_creates_assignment_table() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260917_0008_knowledge_tags.py"
    ).read_text(encoding="utf-8")
    assert '"knowledge_tags"' in migration
    assert '"document_tags"' in migration


def test_space_plans_migration_adds_usage_entitlement_column() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260917_0009_space_plans.py"
    ).read_text(encoding="utf-8")
    assert '"plan"' in migration
    assert "FREE" in migration and "PRO" in migration and "TEAM" in migration


def test_document_owner_migration_adds_nullable_user_reference() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260917_0010_document_owners.py"
    ).read_text(encoding="utf-8")
    assert "owner_user_id" in migration
    assert "fk_documents_owner_user" in migration


def test_public_analytics_migration_adds_events_and_moderation_fields() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260917_0011_public_analytics.py"
    ).read_text(encoding="utf-8")
    assert '"public_access_events"' in migration
    assert "is_hidden" in migration
    assert "moderation_note" in migration


def test_knowledge_sources_migration_registers_external_source_state() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260917_0012_knowledge_sources.py"
    ).read_text(encoding="utf-8")
    assert '"knowledge_sources"' in migration
    assert "last_checksum" in migration
    assert "uq_knowledge_sources_space_locator" in migration


def test_share_link_origin_migration_adds_json_allowlist() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260917_0013_share_link_origins.py"
    ).read_text(encoding="utf-8")
    assert '"share_links"' in migration
    assert '"allowed_origins"' in migration
    assert "[]'::jsonb" in migration


def test_eval_set_version_migration_creates_immutable_snapshot_table() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260917_0014_eval_set_versions.py"
    ).read_text(encoding="utf-8")
    assert '"eval_set_versions"' in migration
    assert "cases_snapshot" in migration
    assert "uq_eval_set_versions_space_number" in migration


def test_eval_history_migration_protects_result_rows_from_case_deletion() -> None:
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "versions"
        / "20260917_0015_protect_eval_history.py"
    ).read_text(encoding="utf-8")
    assert "eval_results_eval_case_id_fkey" in migration
    assert 'ondelete="RESTRICT"' in migration
