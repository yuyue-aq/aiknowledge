from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain.spaces import (
    Category,
    CreatedShareLink,
    KnowledgeSpace,
    PublicQuestionRecord,
    PublicContentMode,
    SpacePlan,
    ShareLink,
    ShareLinkStatus,
    SpaceRuleViolationError,
    SpaceVisibility,
)
from app.main import create_app


class FakeSpaceService:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 11, tzinfo=UTC)
        self.space = KnowledgeSpace(
            id=uuid4(),
            name="现有空间",
            description=None,
            visibility=SpaceVisibility.PRIVATE,
            guest_feedback_enabled=False,
            created_at=self.now,
            updated_at=self.now,
        )
        self.category = Category(
            id=uuid4(),
            space_id=self.space.id,
            name="公开分类",
            description=None,
            is_open=True,
            sort_order=0,
            created_at=self.now,
            updated_at=self.now,
        )
        self.link = ShareLink(
            id=uuid4(),
            space_id=self.space.id,
            category_ids=(self.category.id,),
            token_hash="never-return-this-hash",
            status=ShareLinkStatus.ACTIVE,
            created_at=self.now,
        )
        self.share_options: dict[str, object] = {}

    async def list_spaces(self) -> list[KnowledgeSpace]:
        return [self.space]

    async def create_space(self, **kwargs: object) -> KnowledgeSpace:
        self.space = KnowledgeSpace(
            id=self.space.id,
            name=kwargs["name"],  # type: ignore[arg-type]
            description=kwargs["description"],  # type: ignore[arg-type]
            visibility=kwargs["visibility"],  # type: ignore[arg-type]
            guest_feedback_enabled=kwargs["guest_feedback_enabled"],  # type: ignore[arg-type]
            created_at=self.now,
            updated_at=self.now,
        )
        return self.space

    async def create_category(self, **_: object) -> Category:
        raise SpaceRuleViolationError("只有公开空间可以创建分类。")

    async def create_share_link(self, **kwargs: object) -> CreatedShareLink:
        self.share_options = kwargs
        return CreatedShareLink(
            link=replace(self.link, content_mode=kwargs.get("content_mode", PublicContentMode.DOCUMENTS)),
            token="only-returned-once-token",
        )

    async def list_share_links(self, _: UUID) -> list[ShareLink]:
        return [self.link]


@pytest.mark.asyncio
async def test_spaces_api_creates_space_and_returns_typed_owner_data() -> None:
    service = FakeSpaceService()
    app = create_app(
        rag_service=object(), space_service_factory=lambda _: service
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/spaces",
            json={
                "name": "发布资料库",
                "description": "公开产品知识",
                "visibility": "PUBLIC",
                "guest_feedback_enabled": True,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "发布资料库"
    assert body["visibility"] == "PUBLIC"
    assert body["guest_feedback_enabled"] is True
    assert UUID(body["id"]) == service.space.id


@pytest.mark.asyncio
async def test_spaces_api_maps_business_rule_errors_to_the_standard_protocol() -> None:
    service = FakeSpaceService()
    app = create_app(
        rag_service=object(), space_service_factory=lambda _: service
    )
    request_id = "fa13fa85-05f0-4d7d-b208-9ecbf1b8ed4a"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/v1/spaces/{service.space.id}/categories",
            headers={"X-Request-ID": request_id},
            json={"name": "制度", "is_open": True},
        )

    assert response.status_code == 409
    assert response.json() == {
        "code": "SPACE_RULE_VIOLATION",
        "message": "只有公开空间可以创建分类。",
        "request_id": request_id,
        "details": None,
    }


@pytest.mark.asyncio
async def test_share_link_api_returns_raw_token_once_and_never_serializes_token_hash() -> None:
    service = FakeSpaceService()
    app = create_app(
        rag_service=object(), space_service_factory=lambda _: service
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/api/v1/spaces/{service.space.id}/share-links",
            json={"category_ids": [str(service.category.id)]},
        )
        listed = await client.get(f"/api/v1/spaces/{service.space.id}/share-links")

    assert created.status_code == 201
    assert created.json()["token"] == "only-returned-once-token"
    assert "token_hash" not in created.json()["link"]
    assert listed.status_code == 200
    assert "token" not in listed.json()["items"][0]
    assert "token_hash" not in listed.json()["items"][0]


@pytest.mark.asyncio
async def test_share_link_api_preserves_explicit_published_answer_mode() -> None:
    service = FakeSpaceService()
    app = create_app(rag_service=object(), space_service_factory=lambda _: service)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/v1/spaces/{service.space.id}/share-links",
            json={
                "category_ids": [str(service.category.id)],
                "content_mode": "PUBLISHED_ANSWERS",
            },
        )

    assert response.status_code == 201
    assert response.json()["link"]["content_mode"] == "PUBLISHED_ANSWERS"
    assert service.share_options["content_mode"] is PublicContentMode.PUBLISHED_ANSWERS


@pytest.mark.asyncio
async def test_public_question_records_api_returns_anonymized_records() -> None:
    service = FakeSpaceService()
    record = PublicQuestionRecord(
        id=uuid4(),
        share_link_id=service.link.id,
        visitor_id="anonymous",
        conversation_id=None,
        question_hash="b" * 64,
        created_at=service.now,
    )

    class FakeQuestionLogService:
        async def list_questions(self, *_: object, **__: object) -> list[PublicQuestionRecord]:
            return [record]

    app = create_app(rag_service=object(), space_service_factory=lambda _: service)
    app.state.public_question_log_service_factory = lambda _: FakeQuestionLogService()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/api/v1/spaces/{service.space.id}/public-questions")

    assert response.status_code == 200
    assert response.json()["items"][0]["question_hash"] == "b" * 64
    assert "question" not in response.json()["items"][0]


@pytest.mark.asyncio
async def test_spaces_api_updates_demo_plan() -> None:
    service = FakeSpaceService()

    async def update_space(_: UUID, **changes: object) -> KnowledgeSpace:
        if "plan" in changes:
            service.space = replace(service.space, plan=changes["plan"])  # type: ignore[arg-type]
        return service.space

    service.update_space = update_space  # type: ignore[method-assign]
    app = create_app(rag_service=object(), space_service_factory=lambda _: service)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            f"/api/v1/spaces/{service.space.id}", json={"plan": "PRO"}
        )

    assert response.status_code == 200
    assert response.json()["plan"] == SpacePlan.PRO
