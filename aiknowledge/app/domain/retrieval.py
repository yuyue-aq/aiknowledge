from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.conversations import RetrievedChunk


class RetrievalError(RuntimeError):
    """Stable public error; provider and database details remain in its cause."""

    def __init__(self, code: str, message: str, status_code: int = 503):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class RetrievalMetadataFilter:
    """Optional query filters, always applied inside the existing live scope."""

    category_ids: tuple[UUID, ...] = ()
    tag_ids: tuple[UUID, ...] = ()
    formats: tuple[str, ...] = ()
    version_min: int | None = None
    version_max: int | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    _FORMATS = frozenset({"pdf", "docx", "markdown", "text", "table", "presentation"})

    def __post_init__(self) -> None:
        for name in ("category_ids", "tag_ids"):
            values = getattr(self, name)
            if len(values) > 100 or any(not isinstance(value, UUID) for value in values):
                raise ValueError(f"{name} must contain at most 100 UUID values")
            object.__setattr__(self, name, tuple(sorted(set(values), key=str)))

        aliases = {
            "md": "markdown", "markdown": "markdown", "text/markdown": "markdown",
            "txt": "text", "text": "text", "csv": "table", "tsv": "table",
            "xlsx": "table", "table": "table", "pptx": "presentation",
            "presentation": "presentation", "pdf": "pdf", "docx": "docx",
        }
        normalized = []
        for value in self.formats:
            if not isinstance(value, str) or value.strip().lower() not in aliases:
                raise ValueError("formats contains an unsupported document format")
            normalized.append(aliases[value.strip().lower()])
        normalized = sorted(set(normalized))
        if len(normalized) > len(self._FORMATS):
            raise ValueError("formats contains too many values")
        object.__setattr__(self, "formats", tuple(normalized))

        for name in ("version_min", "version_max"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10_000):
                raise ValueError(f"{name} must be between 1 and 10000")
        if self.version_min is not None and self.version_max is not None and self.version_min > self.version_max:
            raise ValueError("version_min must be less than or equal to version_max")

        for name in ("valid_from", "valid_to"):
            value = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must include a timezone")
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_from >= self.valid_to:
                raise ValueError("valid_from must be earlier than valid_to")

    def snapshot(self) -> dict[str, object]:
        return {
            "category_ids": [str(value) for value in self.category_ids],
            "tag_ids": [str(value) for value in self.tag_ids],
            "formats": list(self.formats),
            "version_min": self.version_min,
            "version_max": self.version_max,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
        }

    @classmethod
    def from_snapshot(cls, value: object) -> "RetrievalMetadataFilter":
        if not isinstance(value, dict):
            raise ValueError("metadata filter snapshot must be an object")
        return cls(
            category_ids=tuple(UUID(str(item)) for item in value.get("category_ids", [])),
            tag_ids=tuple(UUID(str(item)) for item in value.get("tag_ids", [])),
            formats=tuple(str(item) for item in value.get("formats", [])),
            version_min=value.get("version_min"),
            version_max=value.get("version_max"),
            valid_from=datetime.fromisoformat(str(value["valid_from"])) if value.get("valid_from") else None,
            valid_to=datetime.fromisoformat(str(value["valid_to"])) if value.get("valid_to") else None,
        )


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    question: str
    top_k: int
    items: tuple[RetrievedChunk, ...]
    timings_ms: dict[str, float]
    branches: dict[str, tuple[RetrievedChunk, ...]] = field(default_factory=dict)
    config_snapshot: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    space_id: UUID
    user_id: UUID
    access_revision: int
    knowledge_revision: int
    resolved_at: datetime
    metadata_filter: RetrievalMetadataFilter = field(default_factory=RetrievalMetadataFilter)

    def same_access(self, other: RetrievalScope) -> bool:
        return (self.space_id, self.user_id, self.access_revision, self.knowledge_revision) == (
            other.space_id, other.user_id, other.access_revision, other.knowledge_revision
        )


@dataclass(frozen=True, slots=True)
class RetrievalRun:
    id: UUID
    scope: RetrievalScope
    question: str
    top_k: int
    chunk_ids: tuple[UUID, ...]
    scores: tuple[float, ...]
    timings_ms: dict[str, float]
    model_name: str
    created_at: datetime
    strategy: str = 'dense'
    config_snapshot: dict[str, object] = field(default_factory=dict)
