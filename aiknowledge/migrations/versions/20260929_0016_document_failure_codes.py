"""Persist scanned-document and recoverable queue failures.

Revision ID: 20260929_0016
Revises: 20260917_0015
"""

from alembic import op
import sqlalchemy as sa

revision = "20260929_0016"
down_revision = "20260917_0015"
branch_labels = None
depends_on = None

LEGACY = (
    "UNSUPPORTED_FILE_TYPE", "EMPTY_DOCUMENT", "ENCRYPTED_PDF",
    "MALFORMED_DOCUMENT", "INVALID_TEXT_ENCODING", "EMBEDDING_FAILED",
)
CURRENT = (*LEGACY, "SCANNED_DOCUMENT", "QUEUE_UNAVAILABLE")


def _constraint(values):
    allowed = ", ".join(f"'{value}'" for value in values)
    op.create_check_constraint(
        "document_failure_code", "documents", sa.text(f"failure_code IN ({allowed})")
    )


def upgrade():
    op.drop_constraint("document_failure_code", "documents", type_="check")
    _constraint(CURRENT)


def downgrade():
    op.drop_constraint("document_failure_code", "documents", type_="check")
    # Retain retryable FAILED rows while mapping to the older vocabulary.
    op.execute("UPDATE documents SET failure_code = 'MALFORMED_DOCUMENT' WHERE failure_code = 'SCANNED_DOCUMENT'")
    op.execute("UPDATE documents SET failure_code = 'EMBEDDING_FAILED' WHERE failure_code = 'QUEUE_UNAVAILABLE'")
    _constraint(LEGACY)
