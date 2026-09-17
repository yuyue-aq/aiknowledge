from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain.sources import KnowledgeSource, SourceKind, SourceStatus, SourceSyncResult
from app.main import create_app


def source(space_id: UUID, *, source_id: UUID | None = None) -> KnowledgeSource:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    return KnowledgeSource(
        id=source_id or uuid4(),
        space_id=space_id,
        kind=SourceKind.WEBPAGE,
        locator="https://example.com/guide",
        name="产品指南",
        status=SourceStatus.ACTIVE,
        last_checksum=None,
        last_synced_at=None,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_source_api_registers_lists_and_syncs_source() -> None:
    space_id = uuid4()
    registered = source(space_id)

    class FakeSourceService:
        async def list_sources(self, requested_space_id: UUID, **_: object):
            assert requested_space_id == space_id
            return [registered]

        async def create_source(self, **_: object):
            return registered

        async def set_status(self, source_id: UUID, **_: object):
            assert source_id == registered.id
            return replace(registered, status=SourceStatus.DISABLED)

        async def sync_source(self, source_id: UUID, **_: object):
            assert source_id == registered.id
            return SourceSyncResult(source=registered, uploaded=2, failed=1, skipped=False)

    app = create_app(rag_service=object(), source_service_factory=lambda _: FakeSourceService())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        listed = await client.get(f"/api/v1/spaces/{space_id}/sources")
        created = await client.post(
            f"/api/v1/spaces/{space_id}/sources",
            json={"kind": "WEBPAGE", "locator": "https://example.com/guide", "name": "产品指南"},
        )
        synced = await client.post(f"/api/v1/sources/{registered.id}/sync")

    assert listed.status_code == 200
    assert listed.json()["items"][0]["kind"] == "WEBPAGE"
    assert created.status_code == 201
    assert created.json()["locator"] == "https://example.com/guide"
    assert synced.status_code == 200
    assert synced.json()["uploaded"] == 2
    assert synced.json()["failed"] == 1


@pytest.mark.asyncio
async def test_source_api_translates_invalid_source_errors() -> None:
    class FakeSourceService:
        async def create_source(self, **_: object):
            raise ValueError("来源地址必须是 http 或 https URL。")

    app = create_app(rag_service=object(), source_service_factory=lambda _: FakeSourceService())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/v1/spaces/{uuid4()}/sources",
            json={"kind": "WEBPAGE", "locator": "file:///tmp/a"},
        )
    assert response.status_code == 422
    assert response.json()["code"] == "SOURCE_INVALID"
