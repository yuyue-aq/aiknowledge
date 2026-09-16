from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.conversations import (
    ConversationKind,
    Feedback,
    FeedbackAccessDeniedError,
    FeedbackGuestDisabledError,
    FeedbackRating,
    FeedbackReason,
    MessageFeedbackContext,
)
from app.domain.spaces import PublicRetrievalScope
from app.services.feedback import FeedbackService


class FakeFeedbackRepository:
    def __init__(self) -> None:
        self.space_id = uuid4()
        self.link_id = uuid4()
        self.message_id = uuid4()
        self.context = MessageFeedbackContext(
            message_id=self.message_id,
            space_id=self.space_id,
            conversation_kind=ConversationKind.PUBLIC,
            share_link_id=self.link_id,
            guest_feedback_enabled=True,
        )
        self.feedback: list[Feedback] = []
        self.commits = 0

    async def get_message_context(self, message_id: UUID) -> MessageFeedbackContext | None:
        return self.context if message_id == self.message_id else None

    async def add_feedback(self, feedback: Feedback) -> None:
        self.feedback.append(feedback)

    async def list_feedback(self, space_id: UUID) -> list[Feedback]:
        return [item for item in self.feedback if item.space_id == space_id]

    async def commit(self) -> None:
        self.commits += 1


def build_service() -> tuple[FeedbackService, FakeFeedbackRepository]:
    repository = FakeFeedbackRepository()
    return (
        FeedbackService(
            repository=repository,
            clock=lambda: datetime(2026, 9, 11, tzinfo=UTC),
        ),
        repository,
    )


@pytest.mark.asyncio
async def test_owner_feedback_persists_reason_and_comment_against_a_message() -> None:
    service, repository = build_service()

    feedback = await service.create_owner_feedback(
        message_id=repository.message_id,
        rating=FeedbackRating.NEEDS_CORRECTION,
        reason=FeedbackReason.SOURCE_MISMATCH,
        comment="引用和结论不一致。",
    )

    assert feedback.is_guest is False
    assert feedback.space_id == repository.space_id
    assert feedback.reason is FeedbackReason.SOURCE_MISMATCH
    assert repository.commits == 1


@pytest.mark.asyncio
async def test_public_feedback_requires_enabled_space_and_matching_live_share_link() -> None:
    service, repository = build_service()
    scope = PublicRetrievalScope(
        share_link_id=repository.link_id,
        space_id=repository.space_id,
        category_ids=(uuid4(),),
    )

    repository.context = replace(repository.context, guest_feedback_enabled=False)
    with pytest.raises(FeedbackGuestDisabledError):
        await service.create_public_feedback(
            message_id=repository.message_id,
            scope=scope,
            rating=FeedbackRating.UP,
            reason=None,
            comment=None,
        )

    repository.context = MessageFeedbackContext(
        message_id=repository.message_id,
        space_id=repository.space_id,
        conversation_kind=ConversationKind.PUBLIC,
        share_link_id=repository.link_id,
        guest_feedback_enabled=True,
    )
    with pytest.raises(FeedbackAccessDeniedError):
        await service.create_public_feedback(
            message_id=repository.message_id,
            scope=PublicRetrievalScope(
                share_link_id=uuid4(),
                space_id=repository.space_id,
                category_ids=(uuid4(),),
            ),
            rating=FeedbackRating.DOWN,
            reason=FeedbackReason.INCOMPLETE,
            comment=None,
        )

    feedback = await service.create_public_feedback(
        message_id=repository.message_id,
        scope=scope,
        rating=FeedbackRating.DOWN,
        reason=FeedbackReason.INCOMPLETE,
        comment="遗漏关键限制。",
    )

    assert feedback.is_guest is True
    assert repository.commits == 1


@pytest.mark.asyncio
async def test_needs_correction_feedback_requires_a_reason() -> None:
    service, repository = build_service()

    with pytest.raises(ValueError, match="原因"):
        await service.create_owner_feedback(
            message_id=repository.message_id,
            rating=FeedbackRating.NEEDS_CORRECTION,
            reason=None,
            comment=None,
        )
