"""Persist completion of deleted document version-source cleanup."""
from alembic import op
import sqlalchemy as sa

revision = '20261001_0021'
down_revision = '20261001_0020'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('documents', sa.Column('cleanup_completed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_documents_cleanup_pending', 'documents', ['deleted_at'],
        postgresql_where=sa.text('deleted_at IS NOT NULL AND cleanup_completed_at IS NULL'))


def downgrade():
    op.drop_index('ix_documents_cleanup_pending', table_name='documents')
    op.drop_column('documents', 'cleanup_completed_at')
