from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain.conversations import Feedback, FeedbackRating, FeedbackReason
from app.domain.spaces import Category, KnowledgeSpace, PublicRetrievalScope, SpaceVisibility
from app.main import create_app


class FakeSpaceService:
    def __init__(self) -> None:
        now = datetime(2026, 9, 11, tzinfo=UTC)
        self.space = KnowledgeSpace(
            id=uuid4(),
            name="公开空间",
            description=None,
            visibility=SpaceVisibility.PUBLIC,
            guest_feedback_enabled=True,
            created_at=now,
            updated_at=now,
        )
        self.category = Category(
            id=uuid4(),
            space_id=self.space.id,
            name="开放分类",
            description=None,
            is_open=True,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )
        self.scope = PublicRetrievalScope(
            share_link_id=uuid4(),
            space_id=self.space.id,
            category_ids=(self.category.id,),
        )

    async def resolve_public_scope(self, _token: str) -> PublicRetrievalScope:
        return self.scope

    async def resolve_public_scope_by_link_id(self, link_id: UUID) -> PublicRetrievalScope:
        assert link_id == self.scope.share_link_id
        return self.scope

    async def get_space(self, _space_id: UUID) -> KnowledgeSpace:
        return self.space

    async def list_categories(self, _space_id: UUID) -> list[Category]:
        return [self.category]


class FakeFeedbackService:
    def __init__(self, space_id: UUID) -> None:
        self.space_id = space_id
        self.items: list[Feedback] = []
        self.public_scopes = []

    async def create_owner_feedback(self, **kwargs: object) -> Feedback:
        return self._create(is_guest=False, **kwargs)

    async def create_public_feedback(self, *, scope: PublicRetrievalScope, **kwargs: object) -> Feedback:
        self.public_scopes.append(scope)
        return self._create(is_guest=True, **kwargs)

    async def list_space_feedback(self, space_id: UUID) -> list[Feedback]:
        return [item for item in self.items if item.space_id == space_id]

    def _create(self, *, is_guest: bool, **kwargs: object) -> Feedback:
        feedback = Feedback(
            id=uuid4(),
            message_id=kwargs["message_id"],  # type: ignore[arg-type]
            space_id=self.space_id,
            rating=kwargs["rating"],  # type: ignore[arg-type]
            reason=kwargs["reason"],  # type: ignore[arg-type]
            comment=kwargs["comment"],  # type: ignore[arg-type]
            is_guest=is_guest,
            created_at=datetime(2026, 9, 11, tzinfo=UTC),
        )
        self.items.append(feedback)
        return feedback


@pytest.mark.asyncio
async def test_feedback_api_separates_owner_and_guest_feedback_paths() -> None:
    spaces = FakeSpaceService()
    feedback = FakeFeedbackService(spaces.space.id)
    app = create_app(
        rag_service=object(),
        space_service_factory=lambda _: spaces,
        feedback_service_factory=lambda _: feedback,
    )
    message_id = uuid4()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        owner = await client.post(
            f"/api/v1/messages/{message_id}/feedback",
            json={
                "rating": "NEEDS_CORRECTION",
                "reason": "SOURCE_MISMATCH",
                "comment": "请修正来源。",
            },
        )
        session = await client.post("/api/v1/public/session", json={"token": "share-token"})
        guest = await client.post(
            f"/api/v1/public/messages/{message_id}/feedback",
            json={"rating": "DOWN", "reason": "INCOMPLETE"},
        )
        listed = await client.get(f"/api/v1/spaces/{spaces.space.id}/feedback")

    assert owner.status_code == 201
    assert owner.json()["is_guest"] is False
    assert session.status_code == 200
    assert guest.status_code == 201
    assert guest.json()["is_guest"] is True
    assert feedback.public_scopes == [spaces.scope]
    assert listed.status_code == 200
    assert [item["rating"] for item in listed.json()["items"]] == [
        "NEEDS_CORRECTION",
        "DOWN",
    ]
