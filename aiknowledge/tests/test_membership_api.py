from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain.users import SpaceMembership, SpaceRole, User, UserStatus
from app.main import create_app


class FakeMembershipService:
    def __init__(self) -> None:
        now = datetime(2026, 9, 17, tzinfo=UTC)
        self.owner = User(uuid4(), "owner@example.com", "负责人", "hash", UserStatus.ACTIVE, now, now)
        self.member = User(uuid4(), "member@example.com", "成员", "hash", UserStatus.ACTIVE, now, now)
        self.space_id = uuid4()
        self.membership = SpaceMembership(self.space_id, self.member.id, SpaceRole.MEMBER, now)

    async def list_members(self, **_: object) -> list[SpaceMembership]:
        return [self.membership]

    async def add_member(self, **_: object) -> SpaceMembership:
        return self.membership

    async def change_role(self, **_: object) -> SpaceMembership:
        return SpaceMembership(self.space_id, self.member.id, SpaceRole.EDITOR, self.membership.created_at)

    async def remove_member(self, **_: object) -> None:
        return None

    async def get_user(self, user_id: UUID) -> User:
        return self.member if user_id == self.member.id else self.owner


class FakeAuthService:
    def __init__(self, user: User) -> None:
        self.user = user

    async def get_user(self, user_id: UUID) -> User:
        assert user_id == self.user.id
        return self.user


@pytest.mark.asyncio
async def test_membership_api_requires_bearer_and_returns_member_profile() -> None:
    memberships = FakeMembershipService()
    auth = FakeAuthService(memberships.owner)
    app = create_app(
        rag_service=object(),
        auth_service_factory=lambda _: auth,
        membership_service_factory=lambda _: memberships,
    )
    token = app.state.access_token_codec.issue(memberships.owner.id)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        missing = await client.get(f"/api/v1/spaces/{memberships.space_id}/members")
        response = await client.get(
            f"/api/v1/spaces/{memberships.space_id}/members",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert missing.status_code == 401
    assert response.status_code == 200
    assert response.json()[0]["email"] == "member@example.com"
