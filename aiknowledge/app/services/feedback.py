from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.conversations import (
    ConversationKind,
    Feedback,
    FeedbackAccessDeniedError,
    FeedbackGuestDisabledError,
    FeedbackMessageNotFoundError,
    FeedbackRating,
    FeedbackReason,
    MessageFeedbackContext,
)
from app.domain.spaces import PublicRetrievalScope


class FeedbackRepository(Protocol):
    async def get_message_context(self, message_id: UUID) -> MessageFeedbackContext | None: ...

    async def add_feedback(self, feedback: Feedback) -> None: ...

    async def list_feedback(self, space_id: UUID) -> list[Feedback]: ...

    async def commit(self) -> None: ...


class FeedbackService:
    """Records owner and scope-checked public feedback against answer messages."""

    def __init__(
        self,
        *,
        repository: FeedbackRepository,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory
        self._clock = clock

    async def create_owner_feedback(
        self,
        *,
        message_id: UUID,
        rating: FeedbackRating,
        reason: FeedbackReason | None,
        comment: str | None,
    ) -> Feedback:
        context = await self._require_message_context(message_id)
        return await self._create(
            context=context,
            rating=rating,
            reason=reason,
            comment=comment,
            is_guest=False,
        )

    async def create_public_feedback(
        self,
        *,
        message_id: UUID,
        scope: PublicRetrievalScope,
        rating: FeedbackRating,
        reason: FeedbackReason | None,
        comment: str | None,
    ) -> Feedback:
        context = await self._require_message_context(message_id)
        if not context.guest_feedback_enabled:
            raise FeedbackGuestDisabledError("当前公开空间未开启访客反馈。")
        if (
            context.conversation_kind is not ConversationKind.PUBLIC
            or context.space_id != scope.space_id
            or context.share_link_id != scope.share_link_id
        ):
            raise FeedbackAccessDeniedError("访客不能反馈当前范围之外的回答。")
        return await self._create(
            context=context,
            rating=rating,
            reason=reason,
            comment=comment,
            is_guest=True,
        )

    async def list_space_feedback(self, space_id: UUID) -> list[Feedback]:
        return await self._repository.list_feedback(space_id)

    async def _create(
        self,
        *,
        context: MessageFeedbackContext,
        rating: FeedbackRating,
        reason: FeedbackReason | None,
        comment: str | None,
        is_guest: bool,
    ) -> Feedback:
        normalized_comment = self._normalize_comment(comment)
        if rating is FeedbackRating.NEEDS_CORRECTION and reason is None:
            raise ValueError("需要修正的反馈必须选择原因。")
        feedback = Feedback(
            id=self._id_factory(),
            message_id=context.message_id,
            space_id=context.space_id,
            rating=rating,
            reason=reason,
            comment=normalized_comment,
            is_guest=is_guest,
            created_at=self._now(),
        )
        await self._repository.add_feedback(feedback)
        await self._repository.commit()
        return feedback

    async def _require_message_context(self, message_id: UUID) -> MessageFeedbackContext:
        context = await self._repository.get_message_context(message_id)
        if context is None:
            raise FeedbackMessageNotFoundError("回答消息不存在。")
        return context

    @staticmethod
    def _normalize_comment(comment: str | None) -> str | None:
        if comment is None:
            return None
        normalized = comment.strip()
        if len(normalized) > 1_000:
            raise ValueError("反馈说明不能超过 1000 个字符。")
        return normalized or None

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
