"""protect historical evaluation results from live case deletion

Revision ID: 20260917_0015
Revises: 20260917_0014
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260917_0015"
down_revision: str | None = "20260917_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The original MVP schema used CASCADE here.  That made deleting an
    # editable case silently erase every historical result that referenced
    # it, even though runs now carry immutable case snapshots.
    op.drop_constraint(
        "eval_results_eval_case_id_fkey",
        "eval_results",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "eval_results_eval_case_id_fkey",
        "eval_results",
        "eval_cases",
        ["eval_case_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "eval_results_eval_case_id_fkey",
        "eval_results",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "eval_results_eval_case_id_fkey",
        "eval_results",
        "eval_cases",
        ["eval_case_id"],
        ["id"],
        ondelete="CASCADE",
    )
