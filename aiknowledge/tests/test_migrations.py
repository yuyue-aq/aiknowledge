from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_alembic_has_one_linear_schema_head_and_preserves_initial_revision() -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert script.get_current_head() == "20260916_0003"
    revision = script.get_revision("20260911_0001")
    assert revision is not None
    assert revision.down_revision is None


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
