from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.conversations import Feedback, FeedbackRating, FeedbackReason
from app.infrastructure.database.feedback_repository import SqlAlchemyFeedbackRepository
from app.infrastructure.database.models import FeedbackRecord


class FakeResult:
    def __init__(self, row) -> None:  # type: ignore[no-untyped-def]
        self.row = row

    def one_or_none(self):  # type: ignore[no-untyped-def]
        return self.row


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.context_row = None
        self.flushes = 0

    def add(self, record: object) -> None:
        self.added.append(record)

    async def execute(self, _statement: object) -> FakeResult:
        return FakeResult(self.context_row)

    async def flush(self) -> None:
        self.flushes += 1


@pytest.mark.asyncio
async def test_feedback_repository_maps_answer_context_and_structured_feedback_record() -> None:
    session = FakeSession()
    repository = SqlAlchemyFeedbackRepository(session)  # type: ignore[arg-type]
    message_id = uuid4()
    space_id = uuid4()
    session.context_row = SimpleNamespace(
        message_id=message_id,
        space_id=space_id,
        kind="PUBLIC",
        share_link_id=uuid4(),
        guest_feedback_enabled=True,
    )
    feedback = Feedback(
        id=uuid4(),
        message_id=message_id,
        space_id=space_id,
        rating=FeedbackRating.NEEDS_CORRECTION,
        reason=FeedbackReason.OUTDATED,
        comment="资料需要更新。",
        is_guest=True,
        created_at=datetime(2026, 9, 11, tzinfo=UTC),
    )

    context = await repository.get_message_context(message_id)
    await repository.add_feedback(feedback)

    assert context is not None
    assert context.space_id == space_id
    assert context.guest_feedback_enabled is True
    assert isinstance(session.added[0], FeedbackRecord)
    assert session.added[0].reason is FeedbackReason.OUTDATED  # type: ignore[attr-defined]
    assert session.added[0].is_guest is True  # type: ignore[attr-defined]
    assert session.flushes == 1


@pytest.mark.asyncio
async def test_owner_feedback_list_includes_saved_question_and_original_answer():
    session = FakeSession()
    now = datetime.now(UTC)
    record = FeedbackRecord(id=uuid4(), message_id=uuid4(), rating=FeedbackRating.NEEDS_CORRECTION,
        reason=FeedbackReason.OUTDATED, comment='更新', is_guest=False, created_at=now,
        review_status='PENDING', data_usage_scope='INTERNAL_ONLY', pii_status='UNKNOWN')
    async def execute(statement):
        assert 'rag_runs' in str(statement)
        return SimpleNamespace(all=lambda: [(record, '试用多久？', '旧回答')])
    session.execute = execute
    result = await SqlAlchemyFeedbackRepository(session).list_feedback(uuid4())
    assert result[0].question == '试用多久？'
    assert result[0].original_answer == '旧回答'
