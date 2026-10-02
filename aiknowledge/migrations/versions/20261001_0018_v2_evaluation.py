"""Preserve evidence labels and per-execution diagnostics; legacy remains unknown."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261001_0018'
down_revision = '20261001_0017'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('eval_cases', sa.Column('answerable', sa.Boolean(), nullable=True))
    op.add_column('eval_cases', sa.Column('expected_behavior', sa.String(40), nullable=True))
    op.add_column('eval_cases', sa.Column('evidence_refs', postgresql.JSONB(), nullable=True))
    op.add_column('eval_results', sa.Column('execution_snapshot', postgresql.JSONB(), nullable=True))
    op.add_column('eval_results', sa.Column('retrieval_metrics', postgresql.JSONB(), nullable=True))
    op.add_column('eval_results', sa.Column('failure_code', sa.String(80), nullable=True))


def downgrade():
    for name in ('failure_code', 'retrieval_metrics', 'execution_snapshot'):
        op.drop_column('eval_results', name)
    for name in ('evidence_refs', 'expected_behavior', 'answerable'):
        op.drop_column('eval_cases', name)
