from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.spaces import SpaceNotFoundError
from app.domain.users import SpaceMembership, SpaceRole, User, UserNotFoundError
from app.services.usage import UsageService


class MembershipRepository(Protocol):
    async def get_space(self, space_id: UUID): ...  # type: ignore[no-untyped-def]

    async def get_user(self, user_id: UUID) -> User | None: ...

    async def get_user_by_email(self, email: str) -> User | None: ...

    async def get_membership(self, *, space_id: UUID, user_id: UUID) -> SpaceMembership | None: ...

    async def list_memberships(self, space_id: UUID) -> list[SpaceMembership]: ...

    async def add_membership(self, membership: SpaceMembership) -> None: ...

    async def update_membership(self, membership: SpaceMembership) -> None: ...

    async def delete_membership(self, *, space_id: UUID, user_id: UUID) -> None: ...


class MembershipAccessDeniedError(PermissionError):
    pass


class MembershipAlreadyExistsError(ValueError):
    pass


class MembershipService:
    def __init__(
        self,
        *,
        repository: MembershipRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        usage_service: UsageService | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._usage_service = usage_service

    async def get_user(self, user_id: UUID) -> User:
        user = await self._repository.get_user(user_id)
        if user is None:
            raise UserNotFoundError("用户不存在。")
        return user

    async def list_members(self, *, space_id: UUID, actor_user_id: UUID) -> list[SpaceMembership]:
        await self._require_role(space_id=space_id, actor_user_id=actor_user_id, minimum=SpaceRole.MEMBER)
        return await self._repository.list_memberships(space_id)

    async def add_member(
        self,
        *,
        space_id: UUID,
        actor_user_id: UUID,
        email: str,
        role: SpaceRole,
    ) -> SpaceMembership:
        await self._require_role(space_id=space_id, actor_user_id=actor_user_id, minimum=SpaceRole.OWNER)
        if role == SpaceRole.OWNER:
            raise MembershipAccessDeniedError("一个空间只能有一个负责人。")
        if self._usage_service is not None:
            await self._usage_service.ensure_member_allowed(
                space_id, owner_user_id=actor_user_id
            )
        user = await self._repository.get_user_by_email(email.strip().lower())
        if user is None:
            raise UserNotFoundError("该邮箱尚未注册，请先邀请对方注册。")
        if not user.is_active:
            raise MembershipAccessDeniedError("该用户账号已停用。")
        existing = await self._repository.get_membership(space_id=space_id, user_id=user.id)
        if existing is not None:
            raise MembershipAlreadyExistsError("该用户已经是空间成员。")
        membership = SpaceMembership(
            space_id=space_id,
            user_id=user.id,
            role=role,
            created_at=self._now(),
        )
        await self._repository.add_membership(membership)
        return membership

    async def change_role(
        self,
        *,
        space_id: UUID,
        actor_user_id: UUID,
        member_user_id: UUID,
        role: SpaceRole,
    ) -> SpaceMembership:
        await self._require_role(space_id=space_id, actor_user_id=actor_user_id, minimum=SpaceRole.OWNER)
        membership = await self._require_membership(space_id=space_id, user_id=member_user_id)
        if membership.role == SpaceRole.OWNER or role == SpaceRole.OWNER:
            raise MembershipAccessDeniedError("负责人角色不能通过成员设置修改。")
        updated = SpaceMembership(
            space_id=membership.space_id,
            user_id=membership.user_id,
            role=role,
            created_at=membership.created_at,
        )
        await self._repository.update_membership(updated)
        return updated

    async def remove_member(
        self, *, space_id: UUID, actor_user_id: UUID, member_user_id: UUID
    ) -> None:
        await self._require_role(space_id=space_id, actor_user_id=actor_user_id, minimum=SpaceRole.OWNER)
        membership = await self._require_membership(space_id=space_id, user_id=member_user_id)
        if membership.role == SpaceRole.OWNER:
            raise MembershipAccessDeniedError("不能移除空间负责人。")
        await self._repository.delete_membership(space_id=space_id, user_id=member_user_id)

    async def _require_role(self, *, space_id: UUID, actor_user_id: UUID, minimum: SpaceRole) -> SpaceMembership:
        space = await self._repository.get_space(space_id)
        if space is None or not space.is_active:
            raise SpaceNotFoundError("知识空间不存在。")
        membership = await self._repository.get_membership(space_id=space_id, user_id=actor_user_id)
        if membership is None and space.owner_user_id == actor_user_id:
            membership = SpaceMembership(
                space_id=space_id,
                user_id=actor_user_id,
                role=SpaceRole.OWNER,
                created_at=space.created_at,
            )
        if membership is None or not self._role_at_least(membership.role, minimum):
            raise MembershipAccessDeniedError("你没有执行此操作的权限。")
        return membership

    async def _require_membership(self, *, space_id: UUID, user_id: UUID) -> SpaceMembership:
        membership = await self._repository.get_membership(space_id=space_id, user_id=user_id)
        if membership is None:
            raise UserNotFoundError("该用户不是当前空间成员。")
        return membership

    @staticmethod
    def _role_at_least(actual: SpaceRole, minimum: SpaceRole) -> bool:
        order = {SpaceRole.MEMBER: 0, SpaceRole.EDITOR: 1, SpaceRole.OWNER: 2}
        return order[actual] >= order[minimum]

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
