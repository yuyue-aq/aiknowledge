from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain.tags import KnowledgeTag
from app.main import create_app


class FakeTagService:
    def __init__(self) -> None:
        self.space_id = uuid4()
        self.tag = KnowledgeTag(
            id=uuid4(),
            space_id=self.space_id,
            name="产品",
            color="#2F6FED",
            created_at=datetime(2026, 9, 17, tzinfo=UTC),
            updated_at=datetime(2026, 9, 17, tzinfo=UTC),
        )
        self.assigned: tuple[UUID, ...] = ()

    async def list_tags(self, space_id: UUID) -> list[KnowledgeTag]:
        return [self.tag] if space_id == self.space_id else []

    async def create_tag(self, *, space_id: UUID, name: str, color: str | None = None) -> KnowledgeTag:
        return self.tag

    async def update_tag(self, tag_id: UUID, *, name: str | None = None, color: str | None = None) -> KnowledgeTag:
        return self.tag

    async def delete_tag(self, tag_id: UUID) -> None:
        pass

    async def set_document_tags(self, *, document_id: UUID, tag_ids: tuple[UUID, ...], space_id: UUID) -> tuple[KnowledgeTag, ...]:
        self.assigned = tag_ids
        return (self.tag,)

    async def get_document_tags(self, document_id: UUID) -> tuple[KnowledgeTag, ...]:
        return (self.tag,) if self.assigned else ()


@pytest.mark.asyncio
async def test_tag_api_lists_and_assigns_tags() -> None:
    service = FakeTagService()
    app = create_app(rag_service=object(), tag_service_factory=lambda _: service)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        listed = await client.get(f"/api/v1/spaces/{service.space_id}/tags")
        assigned = await client.put(
            f"/api/v1/spaces/{service.space_id}/documents/{uuid4()}/tags",
            json={"tag_ids": [str(service.tag.id)]},
        )

    assert listed.status_code == 200
    assert listed.json()["items"][0]["name"] == "产品"
    assert assigned.status_code == 200
    assert assigned.json()["items"][0]["id"] == str(service.tag.id)
