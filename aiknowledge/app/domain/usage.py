from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.domain.spaces import SpacePlan


class UsageLimitKind(StrEnum):
    DOCUMENTS = "DOCUMENTS"
    MEMBERS = "MEMBERS"
    QUESTIONS = "QUESTIONS"


@dataclass(frozen=True, slots=True)
class UsageLimits:
    documents: int
    members: int
    questions_per_day: int


@dataclass(frozen=True, slots=True)
class SpaceUsage:
    space_id: UUID
    plan: SpacePlan
    documents_used: int
    members_used: int
    questions_used_today: int
    limits: UsageLimits

    @property
    def documents_remaining(self) -> int:
        return max(self.limits.documents - self.documents_used, 0)

    @property
    def members_remaining(self) -> int:
        return max(self.limits.members - self.members_used, 0)

    @property
    def questions_remaining_today(self) -> int:
        return max(self.limits.questions_per_day - self.questions_used_today, 0)
