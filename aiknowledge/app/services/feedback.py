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
    FeedbackNotFoundError,
    FeedbackRating,
    FeedbackReason,
    FeedbackReviewStatus,
    MessageFeedbackContext,
)
from app.domain.spaces import PublicRetrievalScope
from app.domain.users import SpaceRole


class FeedbackRepository(Protocol):
    async def has_space_access(self, *, space_id: UUID, user_id: UUID) -> bool: ...

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None: ...

    async def get_message_context(self, message_id: UUID) -> MessageFeedbackContext | None: ...

    async def add_feedback(self, feedback: Feedback) -> None: ...

    async def list_feedback(
        self,
        space_id: UUID,
        *,
        review_status: FeedbackReviewStatus | None = None,
        rating: FeedbackRating | None = None,
        is_guest: bool | None = None,
    ) -> list[Feedback]: ...

    async def get_feedback(self, feedback_id: UUID) -> Feedback | None: ...

    async def update_feedback_review(self, feedback_id: UUID, **changes: object) -> Feedback | None: ...

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
        owner_user_id: UUID | None = None,
    ) -> Feedback:
        context = await self._require_message_context(message_id)
        await self._require_owner_space(context.space_id, owner_user_id=owner_user_id)
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

    async def list_space_feedback(
        self,
        space_id: UUID,
        *,
        review_status: FeedbackReviewStatus | None = None,
        rating: FeedbackRating | None = None,
        is_guest: bool | None = None,
        owner_user_id: UUID | None = None,
    ) -> list[Feedback]:
        await self._require_owner_space(space_id, owner_user_id=owner_user_id)
        return await self._repository.list_feedback(
            space_id,
            review_status=review_status,
            rating=rating,
            is_guest=is_guest,
        )

    async def review_feedback(
        self,
        *,
        feedback_id: UUID,
        review_status: FeedbackReviewStatus,
        corrected_answer: str | None,
        review_note: str | None,
        data_usage_scope: str,
        pii_status: str,
        owner_user_id: UUID | None = None,
    ) -> Feedback:
        feedback = await self._repository.get_feedback(feedback_id)
        if feedback is None:
            raise FeedbackNotFoundError("反馈记录不存在。")
        await self._require_owner_space(
            feedback.space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR
        )
        normalized_answer = self._normalize_text(corrected_answer, 4_000, "修正答案")
        normalized_note = self._normalize_text(review_note, 1_000, "审核说明")
        normalized_scope = data_usage_scope.strip().upper()
        normalized_pii = pii_status.strip().upper()
        if not normalized_scope:
            raise ValueError("请选择反馈数据用途。")
        if not normalized_pii:
            raise ValueError("请选择隐私处理状态。")
        if review_status is FeedbackReviewStatus.FIXED and not normalized_answer:
            raise ValueError("已修正的反馈必须填写修正答案。")
        if review_status is not FeedbackReviewStatus.FIXED:
            normalized_answer = normalized_answer or None
        updated = await self._repository.update_feedback_review(
            feedback_id,
            review_status=review_status,
            corrected_answer=normalized_answer,
            review_note=normalized_note,
            reviewed_at=self._now(),
            data_usage_scope=normalized_scope,
            pii_status=normalized_pii,
        )
        if updated is None:
            raise FeedbackNotFoundError("反馈记录不存在。")
        await self._repository.commit()
        return updated

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

    async def _require_owner_space(
        self,
        space_id: UUID,
        *,
        owner_user_id: UUID | None,
        minimum_role: SpaceRole = SpaceRole.MEMBER,
    ) -> None:
        if owner_user_id is None:
            return
        role_reader = getattr(self._repository, "get_space_role", None)
        if role_reader is not None:
            role = await role_reader(space_id=space_id, user_id=owner_user_id)
            if role is None:
                raise FeedbackNotFoundError("反馈记录不存在。")
            order = {SpaceRole.MEMBER: 0, SpaceRole.EDITOR: 1, SpaceRole.OWNER: 2}
            if order[role] < order[minimum_role]:
                raise FeedbackAccessDeniedError("你没有执行反馈审核的权限。")
            return
        checker = getattr(self._repository, "has_space_access", None)
        if checker is None or not await checker(space_id=space_id, user_id=owner_user_id):
            raise FeedbackNotFoundError("反馈记录不存在。")

    @staticmethod
    def _normalize_text(value: str | None, maximum: int, label: str) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > maximum:
            raise ValueError(f"{label}不能超过 {maximum} 个字符。")
        return normalized or None
