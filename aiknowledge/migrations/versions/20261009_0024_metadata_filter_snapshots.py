"""Invalidate knowledge snapshots when tag metadata changes.

Revision ID: 20261009_0024
Revises: 20261007_0023
"""
from alembic import op

revision = "20261009_0024"
down_revision = "20261007_0023"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE FUNCTION v2_bump_tag_knowledge_revision() RETURNS trigger AS $$
    DECLARE old_space uuid; new_space uuid;
    BEGIN
      IF TG_TABLE_NAME = 'knowledge_tags' THEN
        IF TG_OP <> 'INSERT' THEN old_space := OLD.space_id; END IF;
        IF TG_OP <> 'DELETE' THEN new_space := NEW.space_id; END IF;
      ELSE
        IF TG_OP <> 'INSERT' THEN
          SELECT space_id INTO old_space FROM documents WHERE id = OLD.document_id;
        END IF;
        IF TG_OP <> 'DELETE' THEN
          SELECT space_id INTO new_space FROM documents WHERE id = NEW.document_id;
        END IF;
      END IF;
      UPDATE knowledge_spaces SET knowledge_revision = knowledge_revision + 1
      WHERE id = old_space OR id = new_space;
      RETURN NULL;
    END; $$ LANGUAGE plpgsql''')
    op.execute("CREATE TRIGGER v2_knowledge_tags_revision AFTER INSERT OR UPDATE OR DELETE ON knowledge_tags FOR EACH ROW EXECUTE FUNCTION v2_bump_tag_knowledge_revision()")
    op.execute("CREATE TRIGGER v2_document_tags_revision AFTER INSERT OR UPDATE OR DELETE ON document_tags FOR EACH ROW EXECUTE FUNCTION v2_bump_tag_knowledge_revision()")


def downgrade():
    op.execute("DROP TRIGGER v2_document_tags_revision ON document_tags")
    op.execute("DROP TRIGGER v2_knowledge_tags_revision ON knowledge_tags")
    op.execute("DROP FUNCTION v2_bump_tag_knowledge_revision()")
