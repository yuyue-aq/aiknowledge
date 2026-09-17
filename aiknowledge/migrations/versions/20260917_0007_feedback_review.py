"""Add feedback review and data-governance fields.

Revision ID: 20260917_0007
Revises: 20260917_0006
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0007"
down_revision: str | Sequence[str] | None = "20260917_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "feedback",
        sa.Column(
            "review_status",
            sa.String(length=32),
            server_default="PENDING",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "feedback_review_status",
        "feedback",
        sa.text("review_status IN ('PENDING', 'FIXED', 'DEFERRED')"),
    )
    op.add_column("feedback", sa.Column("corrected_answer", sa.Text(), nullable=True))
    op.add_column("feedback", sa.Column("review_note", sa.String(length=1000), nullable=True))
    op.add_column("feedback", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "feedback",
        sa.Column("data_usage_scope", sa.String(length=32), server_default="INTERNAL_ONLY", nullable=False),
    )
    op.add_column(
        "feedback",
        sa.Column("pii_status", sa.String(length=32), server_default="UNKNOWN", nullable=False),
    )
    op.create_index("ix_feedback_review_status", "feedback", ["review_status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_feedback_review_status", table_name="feedback")
    op.drop_column("feedback", "pii_status")
    op.drop_column("feedback", "data_usage_scope")
    op.drop_column("feedback", "reviewed_at")
    op.drop_column("feedback", "review_note")
    op.drop_column("feedback", "corrected_answer")
    op.drop_constraint("feedback_review_status", "feedback", type_="check")
    op.drop_column("feedback", "review_status")
