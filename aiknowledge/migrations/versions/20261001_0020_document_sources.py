"""Keep version sources independent until atomic activation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261001_0020'
down_revision = '20261001_0019'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('document_versions', sa.Column('source_snapshot', postgresql.JSONB(), nullable=True))
    # Only the current active version has a provable legacy source. Do not
    # invent source metadata for historical versions.
    op.execute("""UPDATE document_versions v SET source_snapshot = jsonb_build_object(
        'storage_key', d.storage_key, 'original_filename', d.original_filename,
        'mime_type', d.mime_type, 'size_bytes', d.size_bytes, 'sha256', d.sha256)
        FROM documents d WHERE d.active_version_id = v.id AND d.deleted_at IS NULL""")


def downgrade():
    op.drop_column('document_versions', 'source_snapshot')
