from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class DocumentFormat(StrEnum):
    PDF = "PDF"
    DOCX = "DOCX"
    MARKDOWN = "MARKDOWN"
    TEXT = "TEXT"


class DocumentFailureCode(StrEnum):
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    ENCRYPTED_PDF = "ENCRYPTED_PDF"
    MALFORMED_DOCUMENT = "MALFORMED_DOCUMENT"
    INVALID_TEXT_ENCODING = "INVALID_TEXT_ENCODING"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"


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


@dataclass(frozen=True, slots=True)
class DocumentSubmission:
    document: StoredDocument
    version: StoredDocumentVersion
    processing_enqueued: bool
