"""Add registered external knowledge sources for manual syncs.

Revision ID: 20260917_0012
Revises: 20260917_0011
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260917_0012"
down_revision: str | Sequence[str] | None = "20260917_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", _enum("source_kind", "WEBPAGE", "MARKDOWN_REPOSITORY", "FAQ_TABLE"), nullable=False),
        sa.Column("locator", sa.String(length=2000), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column(
            "status",
            _enum("source_status", "ACTIVE", "SYNCING", "READY", "FAILED", "DISABLED"),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("last_checksum", sa.String(length=64), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("space_id", "locator", name="uq_knowledge_sources_space_locator"),
    )
    op.create_index(
        "ix_knowledge_sources_space_status",
        "knowledge_sources",
        ["space_id", "status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_sources_space_status", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
