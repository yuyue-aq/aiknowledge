"""Add recoverable asynchronous evaluation progress and fenced leases."""
from alembic import op
import sqlalchemy as sa

revision = '20261001_0019'
down_revision = '20261001_0018'
branch_labels = None
depends_on = None


def upgrade():
    for name in ('progress_total', 'progress_completed'):
        op.add_column('eval_runs', sa.Column(name, sa.Integer(), nullable=False, server_default='0'))
    for name in ('heartbeat_at', 'lease_expires_at'):
        op.add_column('eval_runs', sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    for name in ('lease_owner', 'task_id', 'failure_code'):
        op.add_column('eval_runs', sa.Column(name, sa.String(80), nullable=True))
    op.create_index('ix_eval_runs_recovery', 'eval_runs', ['status', 'lease_expires_at'])


def downgrade():
    op.drop_index('ix_eval_runs_recovery', table_name='eval_runs')
    for name in ('failure_code', 'task_id', 'lease_owner', 'lease_expires_at', 'heartbeat_at', 'progress_completed', 'progress_total'):
        op.drop_column('eval_runs', name)
