"""Add anonymized public analytics and visitor moderation metadata.

Revision ID: 20260917_0011
Revises: 20260917_0010
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260917_0011"
down_revision: str | Sequence[str] | None = "20260917_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "public_question_logs",
        sa.Column("is_hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("public_question_logs", sa.Column("moderation_note", sa.String(length=1000), nullable=True))
    op.add_column("public_question_logs", sa.Column("moderated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_public_question_logs_moderation",
        "public_question_logs",
        ["share_link_id", "is_hidden", "created_at"],
        unique=False,
    )
    op.create_table(
        "public_access_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("share_link_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visitor_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("origin", sa.String(length=512), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["space_id"], ["knowledge_spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["share_link_id"], ["share_links.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_public_access_events_space_created",
        "public_access_events",
        ["space_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_public_access_events_link_type",
        "public_access_events",
        ["share_link_id", "event_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_public_access_events_link_type", table_name="public_access_events")
    op.drop_index("ix_public_access_events_space_created", table_name="public_access_events")
    op.drop_table("public_access_events")
    op.drop_index("ix_public_question_logs_moderation", table_name="public_question_logs")
    op.drop_column("public_question_logs", "moderated_at")
    op.drop_column("public_question_logs", "moderation_note")
    op.drop_column("public_question_logs", "is_hidden")
