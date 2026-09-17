from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain.spaces import (
    PublicAccessEvent,
    PublicAccessEventType,
    PublicQuestionRecord,
)
from app.domain.conversations import RagRun
from app.domain.rag import AnswerStatus
from app.domain.users import SpaceRole
from app.services.public_analytics import (
    PublicAnalyticsAccessDeniedError,
    PublicAnalyticsService,
    PublicQuestionModerationError,
)
from app.main import create_app


class FakeAnalyticsRepository:
    def __init__(self, role: SpaceRole | None = SpaceRole.OWNER) -> None:
        self.role = role
        self.events: list[PublicAccessEvent] = []
        self.questions: list[PublicQuestionRecord] = []
        self.calls: list[tuple[RagRun, AnswerStatus | None]] = []

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        return self.role

    async def add_event(self, event: PublicAccessEvent) -> None:
        self.events.append(event)

    async def list_events(self, *, space_id: UUID, since: datetime) -> list[PublicAccessEvent]:
        return [event for event in self.events if event.space_id == space_id and event.created_at >= since]

    async def list_public_call_stats(self, *, space_id: UUID, since: datetime):
        return [item for item in self.calls if item[0].created_at >= since]

    async def get_question(self, question_id: UUID) -> PublicQuestionRecord | None:
        return next((record for record in self.questions if record.id == question_id), None)

    async def update_question(self, record: PublicQuestionRecord) -> None:
        for index, current in enumerate(self.questions):
            if current.id == record.id:
                self.questions[index] = record
                return


@pytest.mark.asyncio
async def test_public_analytics_records_events_and_aggregates_unique_visitors() -> None:
    repository = FakeAnalyticsRepository()
    service = PublicAnalyticsService(
        repository=repository,
        clock=lambda: datetime(2026, 9, 17, 12, tzinfo=UTC),
    )
    space_id = uuid4()
    await service.record_event(
        space_id=space_id,
        share_link_id=uuid4(),
        visitor_id="visitor-a",
        event_type=PublicAccessEventType.QUESTION,
        origin="https://demo.example",
    )
    await service.record_event(
        space_id=space_id,
        share_link_id=uuid4(),
        visitor_id="visitor-a",
        event_type=PublicAccessEventType.QUESTION,
    )
    await service.record_event(
        space_id=space_id,
        share_link_id=uuid4(),
        visitor_id="visitor-b",
        event_type=PublicAccessEventType.SESSION,
    )

    result = await service.get_analytics(space_id, owner_user_id=uuid4(), days=7)
    assert result.questions == 2
    assert result.sessions == 1
    assert result.unique_visitors == 2
    assert result.daily[0].date == "2026-09-17"
    assert result.daily[0].questions == 2


@pytest.mark.asyncio
async def test_public_analytics_requires_editor_and_validates_window() -> None:
    repository = FakeAnalyticsRepository(role=SpaceRole.MEMBER)
    service = PublicAnalyticsService(repository=repository)
    with pytest.raises(PublicAnalyticsAccessDeniedError, match="权限"):
        await service.get_analytics(uuid4(), owner_user_id=uuid4())
    repository.role = SpaceRole.OWNER
    with pytest.raises(ValueError, match="days"):
        await service.get_analytics(uuid4(), owner_user_id=uuid4(), days=0)


@pytest.mark.asyncio
async def test_public_analytics_aggregates_model_latency_tokens_and_failures() -> None:
    now = datetime(2026, 9, 17, 12, tzinfo=UTC)
    repository = FakeAnalyticsRepository()
    for index, latency in enumerate((100, 300, 900)):
        repository.calls.append(
            (
                RagRun(
                    id=uuid4(),
                    trace_id=uuid4(),
                    message_id=uuid4(),
                    prompt_version="v1",
                    rewritten_question="匿名",
                    model_snapshot={},
                    retrieval_config_snapshot={},
                    retrieved_chunk_ids=(),
                    selected_chunk_ids=(),
                    input_tokens=10 + index,
                    output_tokens=20 + index,
                    first_token_latency_ms=None,
                    total_latency_ms=latency,
                    estimated_cost=0.01 * (index + 1),
                    created_at=now,
                ),
                AnswerStatus.FAILED if index == 2 else AnswerStatus.ANSWERED,
            )
        )
    service = PublicAnalyticsService(
        repository=repository, clock=lambda: now
    )
    result = await service.get_analytics(uuid4())
    assert result.answer_count == 3
    assert result.failed_answers == 1
    assert result.latency_p50_ms == 300
    assert result.latency_p95_ms == 900
    assert result.input_tokens == 33
    assert result.output_tokens == 63
    assert result.estimated_cost == 0.06


@pytest.mark.asyncio
async def test_public_question_can_be_hidden_and_note_is_normalized() -> None:
    record = PublicQuestionRecord(
        id=uuid4(),
        share_link_id=uuid4(),
        visitor_id="visitor",
        conversation_id=None,
        question_hash="a" * 64,
        created_at=datetime(2026, 9, 17, tzinfo=UTC),
    )
    repository = FakeAnalyticsRepository()
    repository.questions.append(record)
    service = PublicAnalyticsService(repository=repository)

    updated = await service.moderate_question(
        record.id,
        owner_user_id=uuid4(),
        is_hidden=True,
        moderation_note="  含有个人信息  ",
    )
    assert updated.is_hidden is True
    assert updated.moderation_note == "含有个人信息"
    assert updated.moderated_at is not None


@pytest.mark.asyncio
async def test_moderation_rejects_missing_question_and_overlong_note() -> None:
    service = PublicAnalyticsService(repository=FakeAnalyticsRepository())
    with pytest.raises(PublicQuestionModerationError, match="不存在"):
        await service.moderate_question(uuid4(), owner_user_id=uuid4(), is_hidden=True)
    with pytest.raises(ValueError, match="1000"):
        await service.moderate_question(
            uuid4(), owner_user_id=uuid4(), is_hidden=False, moderation_note="x" * 1001
        )


@pytest.mark.asyncio
async def test_public_analytics_api_exposes_aggregates_and_moderation_state() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    question_id = uuid4()

    class FakeAnalyticsService:
        async def get_analytics(self, space_id: UUID, **_: object):
            from app.domain.spaces import PublicAnalytics, PublicAnalyticsDay

            return PublicAnalytics(
                space_id=space_id,
                period_start=now - timedelta(days=7),
                period_end=now,
                sessions=3,
                conversations=2,
                questions=5,
                unique_visitors=2,
                daily=(PublicAnalyticsDay("2026-09-17", 3, 2, 5, 2),),
            )

        async def moderate_question(self, question_id: UUID, **kwargs: object):
            return PublicQuestionRecord(
                id=question_id,
                share_link_id=uuid4(),
                visitor_id="visitor",
                conversation_id=None,
                question_hash="c" * 64,
                created_at=now,
                is_hidden=bool(kwargs["is_hidden"]),
                moderation_note=kwargs.get("moderation_note"),
                moderated_at=now,
            )

    app = create_app(
        rag_service=object(),
        public_analytics_service_factory=lambda _: FakeAnalyticsService(),
    )
    space_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        analytics = await client.get(f"/api/v1/spaces/{space_id}/public-analytics?days=7")
        moderated = await client.patch(
            f"/api/v1/public-questions/{question_id}",
            json={"is_hidden": True, "moderation_note": "屏蔽"},
        )
    assert analytics.status_code == 200
    assert analytics.json()["questions"] == 5
    assert analytics.json()["daily"][0]["unique_visitors"] == 2
    assert moderated.status_code == 200
    assert moderated.json()["is_hidden"] is True
