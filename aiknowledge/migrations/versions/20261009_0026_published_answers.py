"""Add reviewed public answers and opt-in share-link retrieval mode.

Revision ID: 20261009_0026
Revises: 20261009_0025
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql


revision = "20261009_0026"
down_revision = "20261009_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "share_links",
        sa.Column("content_mode", sa.String(32), nullable=False, server_default="DOCUMENTS"),
    )
    op.create_check_constraint(
        "ck_share_links_content_mode",
        "share_links",
        "content_mode IN ('DOCUMENTS', 'PUBLISHED_ANSWERS')",
    )
    op.create_table(
        "public_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="DRAFT"),
        sa.Column("source_refs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawal_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'PUBLISHED', 'WITHDRAWN')", name="ck_public_answers_status"),
    )
    op.create_index("ix_public_answers_space_status", "public_answers", ["space_id", "status"])
    op.create_index("ix_public_answers_category", "public_answers", ["space_id", "category_id"])
    op.create_table(
        "public_answer_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("answer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("public_answers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", VECTOR(1024), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="PUBLISHED"),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawal_reason", sa.String(500), nullable=True),
        sa.UniqueConstraint("answer_id", "version_number", name="uq_public_answer_versions_number"),
        sa.CheckConstraint("status IN ('PUBLISHED', 'WITHDRAWN', 'SUPERSEDED')", name="ck_public_answer_versions_status"),
        sa.CheckConstraint("source_count >= 0", name="ck_public_answer_versions_source_count"),
    )
    op.create_index("ix_public_answer_versions_scope", "public_answer_versions", ["space_id", "category_id", "status"])
    op.create_index(
        "uq_public_answer_versions_current", "public_answer_versions", ["answer_id"],
        unique=True, postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
    op.create_table(
        "public_answer_sources",
        sa.Column("answer_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("public_answer_versions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_public_answer_sources_document_version", "public_answer_sources", ["document_id", "document_version_id"])
    op.add_column("citations", sa.Column("public_answer_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_citations_public_answer_version", "citations", "public_answer_versions",
        ["public_answer_version_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_citations_public_answer_version", "citations", ["public_answer_version_id"])

    # A source change withdraws the affected published snapshot in the same transaction.
    op.execute('''CREATE FUNCTION v2_withdraw_public_answers_on_source_change() RETURNS trigger AS $$
    BEGIN
      IF NEW.active_version_id IS DISTINCT FROM OLD.active_version_id THEN
        WITH withdrawn AS (
          UPDATE public_answer_versions AS version
          SET status = 'WITHDRAWN', withdrawn_at = clock_timestamp(),
              withdrawal_reason = 'SOURCE_VERSION_CHANGED'
          WHERE version.status = 'PUBLISHED'
            AND EXISTS (
              SELECT 1 FROM public_answer_sources AS source
              WHERE source.answer_version_id = version.id
                AND source.document_id = NEW.id
                AND source.document_version_id IS DISTINCT FROM NEW.active_version_id
            )
          RETURNING version.answer_id
        )
        UPDATE public_answers AS answer
        SET status = 'WITHDRAWN', withdrawal_reason = 'SOURCE_VERSION_CHANGED',
            updated_at = clock_timestamp()
        WHERE answer.status = 'PUBLISHED'
          AND answer.id IN (SELECT answer_id FROM withdrawn);
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql''')
    op.execute('''CREATE TRIGGER v2_withdraw_public_answers_on_source_change
      AFTER UPDATE OF active_version_id ON documents
      FOR EACH ROW EXECUTE FUNCTION v2_withdraw_public_answers_on_source_change()''')

    # Published content fields are immutable; only lifecycle fields can change.
    op.execute('''CREATE FUNCTION v2_protect_published_answer_version() RETURNS trigger AS $$
    BEGIN
      IF NEW.answer_id IS DISTINCT FROM OLD.answer_id
        OR NEW.space_id IS DISTINCT FROM OLD.space_id
        OR NEW.category_id IS DISTINCT FROM OLD.category_id
        OR NEW.version_number IS DISTINCT FROM OLD.version_number
        OR NEW.question IS DISTINCT FROM OLD.question
        OR NEW.answer IS DISTINCT FROM OLD.answer
        OR NEW.source_count IS DISTINCT FROM OLD.source_count
        OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
        OR NEW.embedding IS DISTINCT FROM OLD.embedding
        OR NEW.reviewed_by IS DISTINCT FROM OLD.reviewed_by
        OR NEW.reviewed_at IS DISTINCT FROM OLD.reviewed_at
        OR NEW.published_by IS DISTINCT FROM OLD.published_by
        OR NEW.published_at IS DISTINCT FROM OLD.published_at THEN
        RAISE EXCEPTION 'published public answer snapshots are immutable';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql''')
    op.execute('''CREATE TRIGGER v2_protect_published_answer_version
      BEFORE UPDATE ON public_answer_versions
      FOR EACH ROW EXECUTE FUNCTION v2_protect_published_answer_version()''')

    op.execute('''CREATE FUNCTION v2_bump_public_answer_revision() RETURNS trigger AS $$
    DECLARE target_space uuid;
    BEGIN
      IF TG_OP = 'DELETE' THEN target_space := OLD.space_id;
      ELSE target_space := NEW.space_id; END IF;
      UPDATE knowledge_spaces SET knowledge_revision = knowledge_revision + 1 WHERE id = target_space;
      RETURN NULL;
    END; $$ LANGUAGE plpgsql''')
    op.execute('''CREATE TRIGGER v2_public_answer_revision
      AFTER INSERT OR UPDATE OR DELETE ON public_answer_versions
      FOR EACH ROW EXECUTE FUNCTION v2_bump_public_answer_revision()''')


def downgrade() -> None:
    op.execute("DROP TRIGGER v2_public_answer_revision ON public_answer_versions")
    op.execute("DROP FUNCTION v2_bump_public_answer_revision()")
    op.execute("DROP TRIGGER v2_protect_published_answer_version ON public_answer_versions")
    op.execute("DROP FUNCTION v2_protect_published_answer_version()")
    op.execute("DROP TRIGGER v2_withdraw_public_answers_on_source_change ON documents")
    op.execute("DROP FUNCTION v2_withdraw_public_answers_on_source_change()")
    op.drop_index("ix_citations_public_answer_version", table_name="citations")
    op.drop_constraint("fk_citations_public_answer_version", "citations", type_="foreignkey")
    op.drop_column("citations", "public_answer_version_id")
    op.drop_index("ix_public_answer_sources_document_version", table_name="public_answer_sources")
    op.drop_table("public_answer_sources")
    op.drop_index("uq_public_answer_versions_current", table_name="public_answer_versions")
    op.drop_index("ix_public_answer_versions_scope", table_name="public_answer_versions")
    op.drop_table("public_answer_versions")
    op.drop_index("ix_public_answers_category", table_name="public_answers")
    op.drop_index("ix_public_answers_space_status", table_name="public_answers")
    op.drop_table("public_answers")
    op.drop_constraint("ck_share_links_content_mode", "share_links", type_="check")
    op.drop_column("share_links", "content_mode")
