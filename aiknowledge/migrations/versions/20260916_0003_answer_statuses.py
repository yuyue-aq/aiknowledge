"""Align persisted answer statuses with the application domain.

Revision ID: 20260916_0003
Revises: 20260914_0002
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260916_0003"
down_revision: str | Sequence[str] | None = "20260914_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CURRENT_STATUSES = (
    "'ANSWERED', 'INSUFFICIENT_EVIDENCE', 'OUT_OF_SCOPE', 'CONFLICT', 'FAILED'"
)
_LEGACY_STATUSES = "'ANSWERED', 'INSUFFICIENT_EVIDENCE', 'UNSAFE_REQUEST'"


def upgrade() -> None:
    # The initial migration predates the durable conversation service and only
    # allowed ANSWERED/INSUFFICIENT_EVIDENCE/UNSAFE_REQUEST.  The service now
    # persists all domain-level terminal states, including a sanitized FAILED
    # result when the model or retrieval dependency is unavailable.
    op.drop_constraint("answer_status", "messages", type_="check")
    op.create_check_constraint(
        "answer_status",
        "messages",
        sa.text(f"answer_status IN ({_CURRENT_STATUSES})"),
    )


def downgrade() -> None:
    op.drop_constraint("answer_status", "messages", type_="check")
    op.create_check_constraint(
        "answer_status",
        "messages",
        sa.text(f"answer_status IN ({_LEGACY_STATUSES})"),
    )
