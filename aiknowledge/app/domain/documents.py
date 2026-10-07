from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class DocumentVersionConflictError(ValueError):
    pass


class DocumentFormat(StrEnum):
    PDF = "PDF"
    DOCX = "DOCX"
    MARKDOWN = "MARKDOWN"
    TEXT = "TEXT"
    TABLE = "TABLE"
    PRESENTATION = "PRESENTATION"


class DocumentFailureCode(StrEnum):
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    SCANNED_DOCUMENT = "SCANNED_DOCUMENT"
    ENCRYPTED_PDF = "ENCRYPTED_PDF"
    MALFORMED_DOCUMENT = "MALFORMED_DOCUMENT"
    INVALID_TEXT_ENCODING = "INVALID_TEXT_ENCODING"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    QUEUE_UNAVAILABLE = "QUEUE_UNAVAILABLE"


class DocumentStatus(StrEnum):
    """The externally visible lifecycle of an uploaded document."""

    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    DELETED = "DELETED"


class DocumentVersionStatus(StrEnum):
    """Lifecycle of a single immutable processing version."""

    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class DocumentTransitionError(ValueError):
    """Raised when a state change could make unverified data retrievable."""


class DocumentAvailabilityError(ValueError):
    """Raised when a document availability window is invalid."""


class DocumentPermissionDeniedError(PermissionError):
    """The caller can see a space but cannot mutate its documents."""


_DOCUMENT_TRANSITIONS: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.PROCESSING: frozenset(
        {DocumentStatus.READY, DocumentStatus.FAILED, DocumentStatus.DELETED}
    ),
    DocumentStatus.READY: frozenset({DocumentStatus.DELETED}),
    DocumentStatus.FAILED: frozenset({DocumentStatus.PROCESSING, DocumentStatus.DELETED}),
    DocumentStatus.DELETED: frozenset(),
}

_DOCUMENT_VERSION_TRANSITIONS: dict[
    DocumentVersionStatus, frozenset[DocumentVersionStatus]
] = {
    DocumentVersionStatus.PROCESSING: frozenset(
        {DocumentVersionStatus.READY, DocumentVersionStatus.FAILED}
    ),
    DocumentVersionStatus.READY: frozenset(),
    DocumentVersionStatus.FAILED: frozenset({DocumentVersionStatus.PROCESSING}),
}


def advance_document_status(
    current: DocumentStatus, target: DocumentStatus
) -> DocumentStatus:
    """Validate one document lifecycle transition.

    A re-index of a ready document is represented by a new document version;
    the ready document stays searchable until that new version is atomically
    activated.  It must not be changed back to ``PROCESSING``.
    """

    if target not in _DOCUMENT_TRANSITIONS[current]:
        raise DocumentTransitionError(
            f"Document transition from {current} to {target} is not allowed."
        )
    return target


def advance_document_version_status(
    current: DocumentVersionStatus, target: DocumentVersionStatus
) -> DocumentVersionStatus:
    """Validate one immutable document-version processing transition."""

    if target not in _DOCUMENT_VERSION_TRANSITIONS[current]:
        raise DocumentTransitionError(
            f"Document version transition from {current} to {target} is not allowed."
        )
    return target


def is_document_retrievable(
    status: DocumentStatus, *, active_version_id: str | None
) -> bool:
    """Require a completed document and an atomically activated version."""

    return status is DocumentStatus.READY and active_version_id is not None


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    text: str
    heading_path: tuple[str, ...]
    ordinal: int
    page_number: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    filename: str
    format: DocumentFormat
    blocks: tuple[DocumentBlock, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks)


@dataclass(frozen=True, slots=True)
class StoredDocument:
    id: UUID
    space_id: UUID
    category_id: UUID | None
    original_filename: str
    storage_key: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: DocumentStatus
    active_version_id: UUID | None
    created_at: datetime
    updated_at: datetime
    failure_code: DocumentFailureCode | None = None
    failure_message: str | None = None
    deleted_at: datetime | None = None
    is_enabled: bool = True
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    owner_user_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class StoredDocumentVersion:
    id: UUID
    document_id: UUID
    version_number: int
    parser_version: str
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    chunk_config: dict[str, object]
    status: DocumentVersionStatus
    created_at: datetime
    activated_at: datetime | None = None
    source_snapshot: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class PersistedChunk:
    id: UUID
    document_id: UUID
    document_version_id: UUID
    space_id: UUID
    category_id: UUID | None
    ordinal: int
    heading_path: tuple[str, ...]
    page_number: int | None
    content: str
    content_hash: str
    token_count: int
    embedding: list[float]
    source_block_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None


@dataclass(frozen=True, slots=True)
class DocumentSubmission:
    document: StoredDocument
    version: StoredDocumentVersion
    processing_enqueued: bool


def is_document_available(document: StoredDocument, *, now: datetime) -> bool:
    """Return whether a ready document is eligible for a new retrieval.

    Availability is evaluated at query time, so toggling a document or changing
    its effective window takes effect without touching already-created chunks.
    All timestamps are normalized to UTC before comparison.
    """

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = now.astimezone(UTC)
    if not is_document_retrievable(
        document.status,
        active_version_id=str(document.active_version_id)
        if document.active_version_id is not None
        else None,
    ):
        return False
    if not document.is_enabled:
        return False
    if document.effective_at is not None and current < _as_utc(document.effective_at):
        return False
    if document.expires_at is not None and current >= _as_utc(document.expires_at):
        return False
    return True


def validate_document_availability(
    *, effective_at: datetime | None, expires_at: datetime | None
) -> None:
    """Validate an optional half-open [effective, expires) availability window."""

    if effective_at is not None and effective_at.tzinfo is None:
        raise DocumentAvailabilityError("生效时间必须包含时区。")
    if expires_at is not None and expires_at.tzinfo is None:
        raise DocumentAvailabilityError("失效时间必须包含时区。")
    if effective_at is not None and expires_at is not None:
        if _as_utc(expires_at) <= _as_utc(effective_at):
            raise DocumentAvailabilityError("失效时间必须晚于生效时间。")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise DocumentAvailabilityError("时间必须包含时区。")
    return value.astimezone(UTC)
