"""Add configurable space plans for usage entitlements.

Revision ID: 20260917_0009
Revises: 20260917_0008
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0009"
down_revision: str | Sequence[str] | None = "20260917_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_spaces",
        sa.Column(
            "plan",
            sa.String(length=16),
            nullable=False,
            server_default="FREE",
        ),
    )
    op.create_check_constraint(
        "ck_knowledge_spaces_plan",
        "knowledge_spaces",
        "plan IN ('FREE', 'PRO', 'TEAM')",
    )
    op.create_index("ix_knowledge_spaces_plan", "knowledge_spaces", ["plan"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_spaces_plan", table_name="knowledge_spaces")
    op.drop_constraint("ck_knowledge_spaces_plan", "knowledge_spaces", type_="check")
    op.drop_column("knowledge_spaces", "plan")
