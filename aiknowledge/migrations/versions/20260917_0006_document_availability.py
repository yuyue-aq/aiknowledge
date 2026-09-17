"""Add document availability controls for lifecycle-safe retrieval.

Revision ID: 20260917_0006
Revises: 20260917_0005
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0006"
down_revision: str | Sequence[str] | None = "20260917_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("documents", sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_documents_availability",
        "documents",
        ["space_id", "is_enabled", "effective_at", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_documents_availability", table_name="documents")
    op.drop_column("documents", "expires_at")
    op.drop_column("documents", "effective_at")
    op.drop_column("documents", "is_enabled")
