"""Distinguish personal/team spaces and support knowledge administrators."""
from alembic import op
import sqlalchemy as sa

revision = '20261002_0022'
down_revision = '20261001_0021'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('knowledge_spaces', sa.Column('kind', sa.String(8), nullable=False,
                                               server_default='PERSONAL'))
    op.create_check_constraint('space_kind', 'knowledge_spaces', "kind IN ('PERSONAL', 'TEAM')")
    # Preserve existing collaboration regardless of the historical quota plan.
    op.execute("""UPDATE knowledge_spaces s SET kind = 'TEAM'
                  WHERE s.plan = 'TEAM' OR EXISTS (
                    SELECT 1 FROM space_memberships m WHERE m.space_id = s.id
                    AND m.role <> 'OWNER')""")
    op.drop_constraint('space_role', 'space_memberships', type_='check')
    op.create_check_constraint('space_role', 'space_memberships',
                               "role IN ('OWNER', 'ADMIN', 'EDITOR', 'MEMBER')")
    # Refuse ambiguous historical ownership rather than silently rewriting it.
    op.create_index('uq_space_memberships_owner', 'space_memberships', ['space_id'],
                    unique=True, postgresql_where=sa.text("role = 'OWNER'"))


def downgrade():
    # Do not silently demote administrators when rolling back.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM space_memberships WHERE role = 'ADMIN') THEN
        RAISE EXCEPTION 'Remove or explicitly demote ADMIN memberships before downgrade';
      END IF;
    END $$""")
    op.drop_index('uq_space_memberships_owner', table_name='space_memberships')
    op.drop_constraint('space_role', 'space_memberships', type_='check')
    op.create_check_constraint('space_role', 'space_memberships', "role IN ('OWNER', 'EDITOR', 'MEMBER')")
    op.drop_constraint('space_kind', 'knowledge_spaces', type_='check')
    op.drop_column('knowledge_spaces', 'kind')
