"""Add public-link controls, presentation metadata and visitor question logs.

Revision ID: 20260917_0005
Revises: 20260917_0004
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260917_0005"
down_revision: str | Sequence[str] | None = "20260917_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("display_name", sa.String(length=120), nullable=True))
    op.add_column("categories", sa.Column("display_description", sa.Text(), nullable=True))
    op.add_column(
        "categories",
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("share_links", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("share_links", sa.Column("visitor_question_limit", sa.Integer(), nullable=True))
    op.create_table(
        "public_question_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("share_link_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visitor_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["share_link_id"], ["share_links.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_public_question_logs_visitor",
        "public_question_logs",
        ["share_link_id", "visitor_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_public_question_logs_visitor", table_name="public_question_logs")
    op.drop_table("public_question_logs")
    op.drop_column("share_links", "visitor_question_limit")
    op.drop_column("share_links", "password_hash")
    op.drop_column("categories", "is_default")
    op.drop_column("categories", "display_description")
    op.drop_column("categories", "display_name")
