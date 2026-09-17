"""Record the user responsible for each uploaded document.

Revision ID: 20260917_0010
Revises: 20260917_0009
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0010"
down_revision: str | Sequence[str] | None = "20260917_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_documents_owner_user",
        "documents",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_documents_owner_user", "documents", ["owner_user_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_documents_owner_user", table_name="documents")
    op.drop_constraint("fk_documents_owner_user", "documents", type_="foreignkey")
    op.drop_column("documents", "owner_user_id")
