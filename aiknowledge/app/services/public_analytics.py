from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.spaces import (
    PublicAccessEvent,
    PublicAccessEventType,
    PublicAnalytics,
    PublicAnalyticsDay,
    PublicQuestionRecord,
)
from app.domain.conversations import RagRun
from app.domain.rag import AnswerStatus
from app.domain.users import SpaceRole


class PublicAnalyticsRepository(Protocol):
    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None: ...

    async def add_event(self, event: PublicAccessEvent) -> None: ...

    async def list_events(self, *, space_id: UUID, since: datetime) -> list[PublicAccessEvent]: ...

    async def list_public_call_stats(
        self, *, space_id: UUID, since: datetime
    ) -> list[tuple[RagRun, AnswerStatus | None]]: ...

    async def get_question(self, question_id: UUID) -> PublicQuestionRecord | None: ...

    async def update_question(self, record: PublicQuestionRecord) -> None: ...


class PublicAnalyticsAccessDeniedError(PermissionError):
    pass


class PublicQuestionModerationError(LookupError):
    pass


class PublicAnalyticsService:
    """Persist privacy-preserving public events and expose operator analytics."""

    def __init__(
        self,
        *,
        repository: PublicAnalyticsRepository,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory
        self._clock = clock

    async def record_event(
        self,
        *,
        space_id: UUID,
        share_link_id: UUID,
        visitor_id: str,
        event_type: PublicAccessEventType,
        origin: str | None = None,
        user_agent: str | None = None,
    ) -> PublicAccessEvent:
        visitor = visitor_id.strip()
        if not visitor or len(visitor) > 128:
            raise ValueError("visitor_id 长度必须在 1 到 128 个字符之间。")
        if origin is not None and len(origin) > 512:
            raise ValueError("origin 不能超过 512 个字符。")
        if user_agent is not None and len(user_agent) > 512:
            raise ValueError("user_agent 不能超过 512 个字符。")
        target_check = getattr(self._repository, "event_targets_exist", None)
        if target_check is not None and not await target_check(
            space_id=space_id, share_link_id=share_link_id
        ):
            # Keep test fixtures and links removed in the same request from
            # turning a best-effort analytics write into a public outage.
            return PublicAccessEvent(
                id=self._id_factory(),
                space_id=space_id,
                share_link_id=share_link_id,
                visitor_id=visitor,
                event_type=event_type,
                origin=origin,
                user_agent=user_agent,
                created_at=self._now(),
            )
        now = self._now()
        event = PublicAccessEvent(
            id=self._id_factory(),
            space_id=space_id,
            share_link_id=share_link_id,
            visitor_id=visitor,
            event_type=event_type,
            origin=origin,
            user_agent=user_agent,
            created_at=now,
        )
        await self._repository.add_event(event)
        return event

    async def get_analytics(
        self,
        space_id: UUID,
        *,
        owner_user_id: UUID | None = None,
        days: int = 30,
    ) -> PublicAnalytics:
        if not 1 <= days <= 90:
            raise ValueError("days must be between 1 and 90")
        if owner_user_id is not None:
            role = await self._repository.get_space_role(
                space_id=space_id, user_id=owner_user_id
            )
            if role is None:
                raise PublicQuestionModerationError("知识空间不存在。")
            if _role_rank(role) < _role_rank(SpaceRole.EDITOR):
                raise PublicAnalyticsAccessDeniedError("当前成员没有查看公开统计的权限。")
        end = self._now()
        start = end - timedelta(days=days)
        events = await self._repository.list_events(space_id=space_id, since=start)
        calls_reader = getattr(self._repository, "list_public_call_stats", None)
        calls = (
            await calls_reader(space_id=space_id, since=start)
            if calls_reader is not None
            else []
        )
        daily_events: dict[str, list[PublicAccessEvent]] = defaultdict(list)
        for event in events:
            if event.created_at < start or event.created_at > end:
                continue
            daily_events[event.created_at.astimezone(UTC).date().isoformat()].append(event)
        sessions = sum(event.event_type is PublicAccessEventType.SESSION for event in events)
        conversations = sum(
            event.event_type is PublicAccessEventType.CONVERSATION for event in events
        )
        questions = sum(event.event_type is PublicAccessEventType.QUESTION for event in events)
        unique_visitors = len({event.visitor_id for event in events})
        daily = tuple(
            PublicAnalyticsDay(
                date=day,
                sessions=sum(item.event_type is PublicAccessEventType.SESSION for item in items),
                conversations=sum(
                    item.event_type is PublicAccessEventType.CONVERSATION for item in items
                ),
                questions=sum(item.event_type is PublicAccessEventType.QUESTION for item in items),
                unique_visitors=len({item.visitor_id for item in items}),
            )
            for day, items in sorted(daily_events.items())
        )
        latencies = sorted(run.total_latency_ms for run, _ in calls)
        answer_count = len(calls)
        failed_answers = sum(status is AnswerStatus.FAILED for _, status in calls)
        return PublicAnalytics(
            space_id=space_id,
            period_start=start,
            period_end=end,
            sessions=sessions,
            conversations=conversations,
            questions=questions,
            unique_visitors=unique_visitors,
            daily=daily,
            answer_count=answer_count,
            failed_answers=failed_answers,
            latency_p50_ms=_percentile(latencies, 0.50),
            latency_p95_ms=_percentile(latencies, 0.95),
            input_tokens=sum(run.input_tokens or 0 for run, _ in calls),
            output_tokens=sum(run.output_tokens or 0 for run, _ in calls),
            estimated_cost=round(sum(run.estimated_cost or 0.0 for run, _ in calls), 8),
        )

    async def moderate_question(
        self,
        question_id: UUID,
        *,
        owner_user_id: UUID | None = None,
        is_hidden: bool,
        moderation_note: str | None = None,
    ) -> PublicQuestionRecord:
        if moderation_note is not None:
            moderation_note = moderation_note.strip() or None
            if moderation_note is not None and len(moderation_note) > 1_000:
                raise ValueError("moderation_note 不能超过 1000 个字符。")
        record = await self._repository.get_question(question_id)
        if record is None:
            raise PublicQuestionModerationError("访客问题记录不存在。")
        if owner_user_id is not None and record.space_id is not None:
            role = await self._repository.get_space_role(
                space_id=record.space_id, user_id=owner_user_id
            )
            if role is None:
                raise PublicQuestionModerationError("知识空间不存在。")
            if _role_rank(role) < _role_rank(SpaceRole.EDITOR):
                raise PublicAnalyticsAccessDeniedError("当前成员没有审核访客问题的权限。")
        updated = PublicQuestionRecord(
            id=record.id,
            share_link_id=record.share_link_id,
            visitor_id=record.visitor_id,
            conversation_id=record.conversation_id,
            question_hash=record.question_hash,
            created_at=record.created_at,
            is_hidden=is_hidden,
            moderation_note=moderation_note,
            moderated_at=self._now(),
            space_id=record.space_id,
        )
        await self._repository.update_question(updated)
        return updated

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)


def _role_rank(role: SpaceRole) -> int:
    return {SpaceRole.MEMBER: 1, SpaceRole.EDITOR: 2, SpaceRole.ADMIN: 3, SpaceRole.OWNER: 4}[role]


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * fraction))))
    return values[index]
