from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class PublicContentMode(StrEnum):
    DOCUMENTS = 'DOCUMENTS'
    PUBLISHED_ANSWERS = 'PUBLISHED_ANSWERS'


class PublicAnswerStatus(StrEnum):
    DRAFT = 'DRAFT'
    IN_REVIEW = 'IN_REVIEW'
    APPROVED = 'APPROVED'
    PUBLISHED = 'PUBLISHED'
    WITHDRAWN = 'WITHDRAWN'


@dataclass(frozen=True, slots=True)
class PublicAnswerSourceRef:
    document_id: UUID
    document_version_id: UUID

    def to_dict(self) -> dict[str, str]:
        return {
            'document_id': str(self.document_id),
            'document_version_id': str(self.document_version_id),
        }


@dataclass(frozen=True, slots=True)
class PublicAnswer:
    id: UUID
    space_id: UUID
    category_id: UUID
    question: str
    answer: str
    status: PublicAnswerStatus
    source_refs: tuple[PublicAnswerSourceRef, ...]
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    updated_by: UUID | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    published_version_id: UUID | None = None
    published_version_number: int | None = None
    withdrawal_reason: str | None = None


class PublicAnswerNotFoundError(LookupError):
    pass


class PublicAnswerRuleViolationError(ValueError):
    pass
