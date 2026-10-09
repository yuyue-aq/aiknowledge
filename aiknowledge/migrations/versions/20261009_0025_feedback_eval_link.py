"""Link corrected feedback to one regression case.

Revision ID: 20261009_0025
Revises: 20261009_0024
"""
from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa


revision = "20261009_0025"
down_revision = "20261009_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_cases",
        sa.Column("source_feedback_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_eval_cases_source_feedback",
        "eval_cases",
        "feedback",
        ["source_feedback_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_eval_cases_source_feedback_id", "eval_cases", ["source_feedback_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_eval_cases_source_feedback_id", "eval_cases", type_="unique")
    op.drop_constraint("fk_eval_cases_source_feedback", "eval_cases", type_="foreignkey")
    op.drop_column("eval_cases", "source_feedback_id")
