from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class SourceKind(StrEnum):
    WEBPAGE = "WEBPAGE"
    MARKDOWN_REPOSITORY = "MARKDOWN_REPOSITORY"
    FAQ_TABLE = "FAQ_TABLE"


class SourceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SYNCING = "SYNCING"
    READY = "READY"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    id: UUID
    space_id: UUID
    kind: SourceKind
    locator: str
    name: str | None
    status: SourceStatus
    last_checksum: str | None
    last_synced_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SourceDocument:
    filename: str
    content: bytes
    content_type: str
    category_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SourceSyncResult:
    source: KnowledgeSource
    uploaded: int
    failed: int
    skipped: bool
