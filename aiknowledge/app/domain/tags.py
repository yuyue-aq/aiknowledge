from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class KnowledgeTag:
    id: UUID
    space_id: UUID
    name: str
    color: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentTagAssignment:
    document_id: UUID
    tag_id: UUID
    created_at: datetime


class TagNotFoundError(LookupError):
    pass


class TagNameConflictError(ValueError):
    pass


class TagValidationError(ValueError):
    pass


class TagPermissionDeniedError(PermissionError):
    """The caller can view a space but cannot mutate its tag taxonomy."""

    pass
