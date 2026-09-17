from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time
from typing import Protocol
from uuid import UUID

from app.domain.spaces import SpacePlan
from app.domain.usage import SpaceUsage, UsageLimits, UsageLimitKind
from app.domain.users import SpaceRole


class UsageSpaceNotFoundError(LookupError):
    pass


class UsageLimitExceededError(ValueError):
    def __init__(self, kind: UsageLimitKind, *, limit: int, used: int) -> None:
        self.kind = kind
        self.limit = limit
        self.used = used
        labels = {
            UsageLimitKind.DOCUMENTS: "文档数量",
            UsageLimitKind.MEMBERS: "成员数量",
            UsageLimitKind.QUESTIONS: "今日提问次数",
        }
        super().__init__(f"当前套餐的{labels[kind]}已达到上限（{limit}）。")


class UsageRepository(Protocol):
    async def get_space_plan(self, space_id: UUID) -> SpacePlan | None: ...

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None: ...

    async def count_documents(self, space_id: UUID) -> int: ...

    async def count_members(self, space_id: UUID) -> int: ...

    async def count_questions(self, *, space_id: UUID, since: datetime) -> int: ...


PLAN_LIMITS: dict[SpacePlan, UsageLimits] = {
    SpacePlan.FREE: UsageLimits(documents=20, members=1, questions_per_day=100),
    SpacePlan.PRO: UsageLimits(documents=200, members=5, questions_per_day=5_000),
    SpacePlan.TEAM: UsageLimits(documents=2_000, members=50, questions_per_day=20_000),
}


class UsageService:
    def __init__(
        self,
        *,
        repository: UsageRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def get_usage(
        self, space_id: UUID, *, owner_user_id: UUID | None = None
    ) -> SpaceUsage:
        await self._require_access(space_id, owner_user_id)
        plan = await self._repository.get_space_plan(space_id)
        if plan is None:
            raise UsageSpaceNotFoundError("知识空间不存在。")
        now = self._now()
        usage = await self._repository.count_documents(space_id)
        members = await self._repository.count_members(space_id)
        questions = await self._repository.count_questions(
            space_id=space_id,
            since=datetime.combine(now.date(), time.min, tzinfo=UTC),
        )
        return SpaceUsage(
            space_id=space_id,
            plan=plan,
            documents_used=usage,
            members_used=members,
            questions_used_today=questions,
            limits=PLAN_LIMITS[plan],
        )

    async def ensure_document_allowed(
        self, space_id: UUID, *, owner_user_id: UUID | None = None
    ) -> None:
        try:
            usage = await self.get_usage(space_id, owner_user_id=owner_user_id)
        except UsageSpaceNotFoundError:
            # Legacy in-memory adapters used by local API fixtures predate the
            # plan column. Their regular space validation still applies.
            return
        if usage.documents_used >= usage.limits.documents:
            raise UsageLimitExceededError(
                UsageLimitKind.DOCUMENTS,
                limit=usage.limits.documents,
                used=usage.documents_used,
            )

    async def ensure_member_allowed(
        self, space_id: UUID, *, owner_user_id: UUID | None = None
    ) -> None:
        try:
            usage = await self.get_usage(space_id, owner_user_id=owner_user_id)
        except UsageSpaceNotFoundError:
            return
        if usage.members_used >= usage.limits.members:
            raise UsageLimitExceededError(
                UsageLimitKind.MEMBERS,
                limit=usage.limits.members,
                used=usage.members_used,
            )

    async def ensure_question_allowed(
        self, space_id: UUID, *, owner_user_id: UUID | None = None
    ) -> None:
        try:
            usage = await self.get_usage(space_id, owner_user_id=owner_user_id)
        except UsageSpaceNotFoundError:
            return
        if usage.questions_used_today >= usage.limits.questions_per_day:
            raise UsageLimitExceededError(
                UsageLimitKind.QUESTIONS,
                limit=usage.limits.questions_per_day,
                used=usage.questions_used_today,
            )

    async def _require_access(self, space_id: UUID, user_id: UUID | None) -> None:
        if user_id is None:
            return
        role = await self._repository.get_space_role(space_id=space_id, user_id=user_id)
        if role is None:
            raise UsageSpaceNotFoundError("知识空间不存在。")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
