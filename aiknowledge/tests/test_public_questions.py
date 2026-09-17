from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.spaces import PublicQuestionRecord, PublicRetrievalScope
from app.domain.users import SpaceRole
from app.services.public_questions import (
    PublicQuestionLimitExceededError,
    PublicQuestionLogService,
    PublicQuestionLimitService,
)


class FakeLogRepository:
    def __init__(self) -> None:
        self.count = 0
        self.hashes: list[str] = []

    async def count_questions(self, **_: object) -> int:
        return self.count

    async def add_question(self, **kwargs: object) -> None:
        self.count += 1
        self.hashes.append(str(kwargs["question_hash"]))


class FakeRecordRepository:
    def __init__(self, *, role: SpaceRole | None = SpaceRole.OWNER) -> None:
        self.role = role
        self.records: list[PublicQuestionRecord] = []

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        return self.role

    async def list_questions(self, *, space_id: UUID, limit: int, offset: int) -> list[PublicQuestionRecord]:
        return self.records[offset : offset + limit]


@pytest.mark.asyncio
async def test_public_question_limit_records_hash_only_and_blocks_next_question() -> None:
    repository = FakeLogRepository()
    service = PublicQuestionLimitService(
        repository=repository,
        clock=lambda: datetime(2026, 9, 17, tzinfo=UTC),
    )
    scope = PublicRetrievalScope(
        share_link_id=uuid4(), space_id=uuid4(), category_ids=(), visitor_id="nonce", visitor_question_limit=1
    )

    await service.check_and_record(scope=scope, conversation_id=uuid4(), question="访客问题")
    assert repository.count == 1
    assert repository.hashes[0] != "访客问题"
    with pytest.raises(PublicQuestionLimitExceededError):
        await service.check_and_record(scope=scope, conversation_id=None, question="第二个问题")


@pytest.mark.asyncio
async def test_unlimited_scope_does_not_write_question_logs() -> None:
    repository = FakeLogRepository()
    service = PublicQuestionLimitService(repository=repository)
    await service.check_and_record(
        scope=PublicRetrievalScope(share_link_id=uuid4(), space_id=uuid4(), category_ids=()),
        conversation_id=None,
        question="问题",
    )
    assert repository.count == 0


@pytest.mark.asyncio
async def test_question_records_are_listed_for_editors_but_not_regular_members() -> None:
    repository = FakeRecordRepository(role=SpaceRole.EDITOR)
    record = PublicQuestionRecord(
        id=uuid4(),
        share_link_id=uuid4(),
        visitor_id="visitor-hash",
        conversation_id=None,
        question_hash="a" * 64,
        created_at=datetime(2026, 9, 17, tzinfo=UTC),
    )
    repository.records.append(record)
    service = PublicQuestionLogService(repository=repository)
    space_id = uuid4()
    owner_id = uuid4()

    listed = await service.list_questions(space_id, owner_user_id=owner_id)
    assert listed == [record]

    repository.role = SpaceRole.MEMBER
    with pytest.raises(PermissionError, match="权限"):
        await service.list_questions(space_id, owner_user_id=owner_id)
