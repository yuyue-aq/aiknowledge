"""add immutable evaluation-set snapshots

Revision ID: 20260917_0014
Revises: 20260917_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260917_0014"
down_revision: str | None = "20260917_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_set_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("cases_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "space_id", "version_number", name="uq_eval_set_versions_space_number"
        ),
    )
    op.create_index(
        "ix_eval_set_versions_space_created",
        "eval_set_versions",
        ["space_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_eval_set_versions_space_created", table_name="eval_set_versions")
    op.drop_table("eval_set_versions")
