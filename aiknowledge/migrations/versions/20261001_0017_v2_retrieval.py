"""Add compatible retrieval audit records and exact source coordinates.

Revision ID: 20261001_0017
Revises: 20260929_0016
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261001_0017'
down_revision = '20260929_0016'
branch_labels = None
depends_on = None


def upgrade():
    for name in ('access_revision', 'knowledge_revision'):
        op.add_column('knowledge_spaces', sa.Column(name, sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('chunks', sa.Column('source_block_id', sa.String(120), nullable=True))
    op.add_column('chunks', sa.Column('char_start', sa.Integer(), nullable=True))
    op.add_column('chunks', sa.Column('char_end', sa.Integer(), nullable=True))
    op.create_table('retrieval_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('space_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('knowledge_spaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('top_k', sa.Integer(), nullable=False),
        sa.Column('access_revision', sa.BigInteger(), nullable=False),
        sa.Column('knowledge_revision', sa.BigInteger(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('chunk_ids', postgresql.JSONB(), nullable=False),
        sa.Column('scores', postgresql.JSONB(), nullable=False),
        sa.Column('timings_ms', postgresql.JSONB(), nullable=False),
        sa.Column('model_name', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_retrieval_runs_owner_space_created', 'retrieval_runs', ['user_id', 'space_id', 'created_at'])
    # Database triggers cover API, Worker, bulk update and recovery paths in the
    # same transaction. Revision increments cannot be lost to concurrent writes.
    op.execute('''CREATE FUNCTION v2_bump_scope_revision() RETURNS trigger AS $$
    DECLARE target_space uuid;
    BEGIN
      IF TG_TABLE_NAME = 'share_link_categories' THEN
        IF TG_OP = 'DELETE' THEN
          SELECT space_id INTO target_space FROM share_links WHERE id = OLD.share_link_id;
        ELSE
          SELECT space_id INTO target_space FROM share_links WHERE id = NEW.share_link_id;
        END IF;
      ELSE
        IF TG_OP = 'DELETE' THEN target_space := OLD.space_id;
        ELSE target_space := NEW.space_id; END IF;
      END IF;
      IF TG_ARGV[0] IN ('access', 'both') THEN
        UPDATE knowledge_spaces SET access_revision = access_revision + 1 WHERE id = target_space;
      END IF;
      IF TG_ARGV[0] IN ('knowledge', 'both') THEN
        UPDATE knowledge_spaces SET knowledge_revision = knowledge_revision + 1 WHERE id = target_space;
      END IF;
      RETURN NULL;
    END; $$ LANGUAGE plpgsql''')
    op.execute('''CREATE FUNCTION v2_space_visibility_revision() RETURNS trigger AS $$
    BEGIN
      IF NEW.visibility IS DISTINCT FROM OLD.visibility OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at THEN
        NEW.access_revision := OLD.access_revision + 1;
      END IF;
      IF NEW.deleted_at IS DISTINCT FROM OLD.deleted_at THEN
        NEW.knowledge_revision := OLD.knowledge_revision + 1;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql''')
    triggers = (
        ('documents', 'AFTER UPDATE OF status, active_version_id, category_id, is_enabled, effective_at, expires_at, deleted_at', 'knowledge'),
        ('categories', 'AFTER UPDATE OF is_open, deleted_at, space_id', 'both'),
        ('share_links', 'AFTER INSERT OR UPDATE OR DELETE', 'access'),
        ('share_link_categories', 'AFTER INSERT OR UPDATE OR DELETE', 'access'),
        ('space_memberships', 'AFTER INSERT OR UPDATE OR DELETE', 'access'),
    )
    for table, event, kind in triggers:
        op.execute(f"CREATE TRIGGER v2_{table}_revision {event} ON {table} FOR EACH ROW EXECUTE FUNCTION v2_bump_scope_revision('{kind}')")
    op.execute('CREATE TRIGGER v2_spaces_revision BEFORE UPDATE OF visibility, deleted_at ON knowledge_spaces FOR EACH ROW EXECUTE FUNCTION v2_space_visibility_revision()')


def downgrade():
    for table in ('documents', 'categories', 'share_links', 'share_link_categories', 'space_memberships'):
        op.execute(f'DROP TRIGGER v2_{table}_revision ON {table}')
    op.execute('DROP TRIGGER v2_spaces_revision ON knowledge_spaces')
    op.execute('DROP FUNCTION v2_bump_scope_revision()')
    op.execute('DROP FUNCTION v2_space_visibility_revision()')
    op.drop_index('ix_retrieval_runs_owner_space_created', table_name='retrieval_runs')
    op.drop_table('retrieval_runs')
    for name in ('char_end', 'char_start', 'source_block_id'):
        op.drop_column('chunks', name)
    for name in ('knowledge_revision', 'access_revision'):
        op.drop_column('knowledge_spaces', name)
