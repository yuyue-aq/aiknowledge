from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.conversations import (
    Feedback,
    FeedbackRating,
    FeedbackReason,
    FeedbackReviewStatus,
)
from app.services.feedback import FeedbackService


def build_feedback() -> Feedback:
    return Feedback(
        id=uuid4(),
        message_id=uuid4(),
        space_id=uuid4(),
        rating=FeedbackRating.NEEDS_CORRECTION,
        reason=FeedbackReason.INCOMPLETE,
        comment="补充流程",
        is_guest=False,
        created_at=datetime(2026, 9, 17, tzinfo=UTC),
    )


class FakeRepository:
    def __init__(self, feedback: Feedback) -> None:
        self.feedback = feedback
        self.commits = 0

    async def get_feedback(self, feedback_id: UUID) -> Feedback | None:
        return self.feedback if feedback_id == self.feedback.id else None

    async def update_feedback_review(self, feedback_id: UUID, **changes: object) -> Feedback | None:
        if feedback_id != self.feedback.id:
            return None
        self.feedback = replace(self.feedback, **changes)
        return self.feedback

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_review_feedback_stores_correction_and_marks_fixed() -> None:
    repository = FakeRepository(build_feedback())
    service = FeedbackService(repository=repository)

    updated = await service.review_feedback(
        feedback_id=repository.feedback.id,
        review_status=FeedbackReviewStatus.FIXED,
        corrected_answer="补充后的完整回答",
        review_note="已补充文档依据",
        data_usage_scope="EVALUATION",
        pii_status="CLEAR",
    )

    assert updated.review_status is FeedbackReviewStatus.FIXED
    assert updated.corrected_answer == "补充后的完整回答"
    assert updated.data_usage_scope == "EVALUATION"
    assert updated.pii_status == "CLEAR"
    assert updated.reviewed_at is not None
    assert repository.commits == 1


@pytest.mark.asyncio
async def test_fixed_review_requires_corrected_answer() -> None:
    repository = FakeRepository(build_feedback())
    service = FeedbackService(repository=repository)

    with pytest.raises(ValueError):
        await service.review_feedback(
            feedback_id=repository.feedback.id,
            review_status=FeedbackReviewStatus.FIXED,
            corrected_answer=None,
            review_note=None,
            data_usage_scope="INTERNAL_ONLY",
            pii_status="UNKNOWN",
        )
