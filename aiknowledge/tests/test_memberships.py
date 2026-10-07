from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.spaces import KnowledgeSpace, SpaceVisibility, SpaceKind
from app.domain.users import SpaceMembership, SpaceRole, User, UserStatus
from app.services.memberships import (
    MembershipAccessDeniedError,
    MembershipAlreadyExistsError,
    MembershipService,
)


class FakeMembershipRepository:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 17, tzinfo=UTC)
        self.owner = User(uuid4(), "owner@example.com", "负责人", "hash", UserStatus.ACTIVE, self.now, self.now)
        self.member = User(uuid4(), "member@example.com", "成员", "hash", UserStatus.ACTIVE, self.now, self.now)
        self.space = KnowledgeSpace(
            id=uuid4(), name="空间", description=None, visibility=SpaceVisibility.PRIVATE,
            guest_feedback_enabled=False, created_at=self.now, updated_at=self.now,
            owner_user_id=self.owner.id,
            kind=SpaceKind.TEAM,
        )
        self.memberships: dict[tuple[UUID, UUID], SpaceMembership] = {
            (self.space.id, self.owner.id): SpaceMembership(self.space.id, self.owner.id, SpaceRole.OWNER, self.now)
        }

    async def get_space(self, space_id: UUID):
        return self.space if space_id == self.space.id else None

    async def get_user(self, user_id: UUID) -> User | None:
        return next((u for u in (self.owner, self.member) if u.id == user_id), None)

    async def get_user_by_email(self, email: str) -> User | None:
        return next((u for u in (self.owner, self.member) if u.email == email), None)

    async def get_membership(self, *, space_id: UUID, user_id: UUID) -> SpaceMembership | None:
        return self.memberships.get((space_id, user_id))

    async def list_memberships(self, space_id: UUID) -> list[SpaceMembership]:
        return [item for (sid, _), item in self.memberships.items() if sid == space_id]

    async def add_membership(self, membership: SpaceMembership) -> None:
        self.memberships[(membership.space_id, membership.user_id)] = membership

    async def update_membership(self, membership: SpaceMembership) -> None:
        self.memberships[(membership.space_id, membership.user_id)] = membership

    async def delete_membership(self, *, space_id: UUID, user_id: UUID) -> None:
        self.memberships.pop((space_id, user_id), None)


@pytest.mark.asyncio
async def test_owner_can_add_and_downgrade_a_registered_member() -> None:
    repository = FakeMembershipRepository()
    service = MembershipService(repository=repository, clock=lambda: repository.now)

    created = await service.add_member(
        space_id=repository.space.id,
        actor_user_id=repository.owner.id,
        email=repository.member.email,
        role=SpaceRole.EDITOR,
    )
    assert created.role is SpaceRole.EDITOR

    changed = await service.change_role(
        space_id=repository.space.id,
        actor_user_id=repository.owner.id,
        member_user_id=repository.member.id,
        role=SpaceRole.MEMBER,
    )
    assert changed.role is SpaceRole.MEMBER


@pytest.mark.asyncio
async def test_duplicate_or_cross_space_member_mutations_are_rejected() -> None:
    repository = FakeMembershipRepository()
    service = MembershipService(repository=repository)

    with pytest.raises(MembershipAlreadyExistsError):
        await service.add_member(
            space_id=repository.space.id,
            actor_user_id=repository.owner.id,
            email=repository.owner.email,
            role=SpaceRole.MEMBER,
        )

    with pytest.raises(MembershipAccessDeniedError):
        await service.list_members(space_id=repository.space.id, actor_user_id=repository.member.id)


@pytest.mark.asyncio
async def test_personal_space_rejects_additional_administrators_and_members():
    repository = FakeMembershipRepository()
    repository.space = replace(repository.space, kind=SpaceKind.PERSONAL)
    service = MembershipService(repository=repository)
    for role in (SpaceRole.ADMIN, SpaceRole.EDITOR, SpaceRole.MEMBER):
        with pytest.raises(MembershipAccessDeniedError, match="个人空间"):
            await service.add_member(space_id=repository.space.id, actor_user_id=repository.owner.id,
                                     email=repository.member.email, role=role)
    assert len(repository.memberships) == 1


@pytest.mark.asyncio
async def test_team_administrator_can_manage_knowledge_but_cannot_manage_members_or_become_owner():
    repository = FakeMembershipRepository()
    service = MembershipService(repository=repository)
    member = await service.add_member(space_id=repository.space.id, actor_user_id=repository.owner.id,
                                      email=repository.member.email, role=SpaceRole.ADMIN)
    assert member.role is SpaceRole.ADMIN
    assert service._role_at_least(SpaceRole.ADMIN, SpaceRole.EDITOR)
    assert not service._role_at_least(SpaceRole.ADMIN, SpaceRole.OWNER)
    with pytest.raises(MembershipAccessDeniedError):
        await service.change_role(space_id=repository.space.id, actor_user_id=repository.member.id,
                                  member_user_id=repository.member.id, role=SpaceRole.OWNER)
    with pytest.raises(MembershipAccessDeniedError):
        await service.change_role(space_id=repository.space.id, actor_user_id=repository.owner.id,
                                  member_user_id=repository.member.id, role=SpaceRole.OWNER)
    changed = await service.change_role(space_id=repository.space.id, actor_user_id=repository.owner.id,
                                       member_user_id=repository.member.id, role=SpaceRole.MEMBER)
    assert changed.role is SpaceRole.MEMBER
