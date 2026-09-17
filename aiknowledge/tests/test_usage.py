from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.spaces import SpacePlan
from app.domain.usage import UsageLimitKind
from app.domain.users import SpaceRole
from app.services.usage import UsageLimitExceededError, UsageService


class FakeUsageRepository:
    def __init__(self, *, plan: SpacePlan = SpacePlan.FREE) -> None:
        self.space_id = uuid4()
        self.plan = plan
        self.role = SpaceRole.OWNER
        self.documents = 0
        self.members = 1
        self.questions = 0

    async def get_space_plan(self, space_id: UUID) -> SpacePlan | None:
        return self.plan if space_id == self.space_id else None

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        return self.role if space_id == self.space_id else None

    async def count_documents(self, space_id: UUID) -> int:
        return self.documents

    async def count_members(self, space_id: UUID) -> int:
        return self.members

    async def count_questions(self, *, space_id: UUID, since: datetime) -> int:
        return self.questions


@pytest.mark.asyncio
async def test_usage_reports_plan_limits_and_remaining_values() -> None:
    repository = FakeUsageRepository(plan=SpacePlan.PRO)
    repository.documents = 4
    repository.members = 2
    repository.questions = 17
    service = UsageService(
        repository=repository,
        clock=lambda: datetime(2026, 9, 17, 12, 0, tzinfo=UTC),
    )

    usage = await service.get_usage(repository.space_id, owner_user_id=uuid4())

    assert usage.plan is SpacePlan.PRO
    assert usage.documents_remaining == 196
    assert usage.members_remaining == 3
    assert usage.questions_remaining_today == 4_983


@pytest.mark.asyncio
async def test_usage_blocks_documents_at_free_plan_limit() -> None:
    repository = FakeUsageRepository()
    repository.documents = 20
    service = UsageService(repository=repository)

    with pytest.raises(UsageLimitExceededError) as error:
        await service.ensure_document_allowed(repository.space_id)

    assert error.value.kind is UsageLimitKind.DOCUMENTS
    assert error.value.limit == 20
