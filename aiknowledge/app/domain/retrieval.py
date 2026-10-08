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
class RetrievalResult:
    question: str
    top_k: int
    items: tuple[RetrievedChunk, ...]
    timings_ms: dict[str, float]
    branches: dict[str, tuple[RetrievedChunk, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    space_id: UUID
    user_id: UUID
    access_revision: int
    knowledge_revision: int
    resolved_at: datetime

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
