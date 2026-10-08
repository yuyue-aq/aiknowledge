"""Persist explicit retrieval strategy and lexical scoring configuration."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision='20261007_0023'
down_revision='20261002_0022'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('retrieval_runs',sa.Column('strategy',sa.String(16),nullable=False,server_default='dense'))
    op.add_column('retrieval_runs',sa.Column('config_snapshot',postgresql.JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")))


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM retrieval_runs WHERE strategy <> 'dense') THEN
        RAISE EXCEPTION 'Archive lexical retrieval runs explicitly before downgrade';
      END IF;
    END $$""")
    op.drop_column('retrieval_runs','config_snapshot')
    op.drop_column('retrieval_runs','strategy')
