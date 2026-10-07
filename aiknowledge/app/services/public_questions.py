from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.spaces import (
    PublicAccessEvent,
    PublicAccessEventType,
    PublicQuestionRecord,
    PublicRetrievalScope,
)
from app.domain.users import SpaceRole
from app.services.usage import UsageService


class PublicQuestionLimitExceededError(PermissionError):
    pass


class PublicQuestionLogRepository(Protocol):
    async def count_questions(self, *, share_link_id: UUID, visitor_id: str) -> int: ...

    async def add_question(
        self,
        *,
        log_id: UUID,
        share_link_id: UUID,
        visitor_id: str,
        conversation_id: UUID | None,
        question_hash: str,
        created_at: datetime,
    ) -> None: ...

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None: ...

    async def list_questions(
        self, *, space_id: UUID, limit: int, offset: int
    ) -> list[PublicQuestionRecord]: ...


class PublicQuestionLogNotFoundError(LookupError):
    pass


class PublicQuestionLogAccessDeniedError(PermissionError):
    pass


class PublicQuestionLimitService:
    def __init__(
        self,
        *,
        repository: PublicQuestionLogRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        usage_service: UsageService | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._usage_service = usage_service

    async def check_and_record(
        self,
        *,
        scope: PublicRetrievalScope,
        conversation_id: UUID | None,
        question: str,
    ) -> None:
        if scope.visitor_question_limit is None:
            # Space-level plans still apply when a link has no per-link cap.
            if self._usage_service is None:
                await self._record_event(scope=scope, conversation_id=conversation_id)
                return
            await self._usage_service.ensure_question_allowed(scope.space_id)
            await self._record_event(scope=scope, conversation_id=conversation_id)
            return
        if self._usage_service is not None:
            await self._usage_service.ensure_question_allowed(scope.space_id)
        visitor_id = scope.visitor_id or "anonymous"
        used = await self._repository.count_questions(
            share_link_id=scope.share_link_id,
            visitor_id=visitor_id,
        )
        if used >= scope.visitor_question_limit:
            raise PublicQuestionLimitExceededError("该分享链接的访客提问次数已用完。")
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        await self._repository.add_question(
            log_id=uuid4(),
            share_link_id=scope.share_link_id,
            visitor_id=visitor_id,
            conversation_id=conversation_id,
            question_hash=hashlib.sha256(question.strip().encode("utf-8")).hexdigest(),
            created_at=now.astimezone(UTC),
        )
        await self._record_event(scope=scope, conversation_id=conversation_id, created_at=now)

    async def _record_event(
        self,
        *,
        scope: PublicRetrievalScope,
        conversation_id: UUID | None,
        created_at: datetime | None = None,
    ) -> None:
        """Persist an analytics event when the backing repository supports it.

        The optional capability keeps lightweight in-memory repositories used by
        tests and local fixtures backwards compatible while production adapters
        persist the event in the same request transaction.
        """
        recorder = getattr(self._repository, "add_event", None)
        if recorder is None:
            return
        target_check = getattr(self._repository, "event_targets_exist", None)
        if target_check is not None and not await target_check(
            space_id=scope.space_id, share_link_id=scope.share_link_id
        ):
            # Compatibility with lightweight fixtures and stale links: an
            # analytics event must never make an otherwise valid answer fail.
            return
        visitor_id = scope.visitor_id or "anonymous"
        timestamp = created_at or self._clock()
        if timestamp.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        await recorder(
            PublicAccessEvent(
                id=uuid4(),
                space_id=scope.space_id,
                share_link_id=scope.share_link_id,
                visitor_id=visitor_id,
                event_type=PublicAccessEventType.QUESTION,
                origin=None,
                user_agent=None,
                created_at=timestamp.astimezone(UTC),
            )
        )


class PublicQuestionLogService:
    """Lists anonymized public question records for space operators."""

    def __init__(self, *, repository: PublicQuestionLogRepository) -> None:
        self._repository = repository

    async def list_questions(
        self,
        space_id: UUID,
        *,
        owner_user_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PublicQuestionRecord]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("offset must not be negative")
        if owner_user_id is not None:
            role = await self._repository.get_space_role(
                space_id=space_id, user_id=owner_user_id
            )
            if role is None:
                raise PublicQuestionLogNotFoundError("知识空间不存在。")
            if _role_rank(role) < _role_rank(SpaceRole.EDITOR):
                raise PublicQuestionLogAccessDeniedError("当前成员没有查看访客提问记录的权限。")
        return await self._repository.list_questions(
            space_id=space_id, limit=limit, offset=offset
        )


def _role_rank(role: SpaceRole) -> int:
    return {SpaceRole.MEMBER: 1, SpaceRole.EDITOR: 2, SpaceRole.ADMIN: 3, SpaceRole.OWNER: 4}[role]
