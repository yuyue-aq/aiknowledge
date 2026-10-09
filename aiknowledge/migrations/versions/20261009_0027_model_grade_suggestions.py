"""Store reproducible model grading suggestions without changing human reviews.

Revision ID: 20261009_0027
Revises: 20261009_0026
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261009_0027"
down_revision = "20261009_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_results",
        sa.Column(
            "model_grade_suggestions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("eval_results", "model_grade_suggestions")
