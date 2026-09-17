from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from app.domain.spaces import SpacePlan
from app.domain.usage import SpaceUsage, UsageLimits
from app.main import create_app


class FakeUsageService:
    def __init__(self) -> None:
        self.space_id = uuid4()

    async def get_usage(self, space_id, *, owner_user_id=None):  # type: ignore[no-untyped-def]
        assert space_id == self.space_id
        return SpaceUsage(
            space_id=space_id,
            plan=SpacePlan.PRO,
            documents_used=3,
            members_used=2,
            questions_used_today=17,
            limits=UsageLimits(documents=200, members=5, questions_per_day=5_000),
        )


@pytest.mark.asyncio
async def test_usage_api_exposes_used_and_remaining_entitlements() -> None:
    service = FakeUsageService()
    app = create_app(rag_service=object(), usage_service_factory=lambda _: service)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/api/v1/spaces/{service.space_id}/usage")

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "PRO"
    assert body["documents_remaining"] == 197
    assert body["questions_remaining_today"] == 4_983
