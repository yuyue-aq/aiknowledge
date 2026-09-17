from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.spaces import (
    Category,
    KnowledgeSpace,
    PublicAccessDeniedError,
    ShareLink,
    SpaceNotFoundError,
    SpaceAccessDeniedError,
    SpaceRuleViolationError,
    SpacePlan,
    SpaceVisibility,
)
from app.domain.users import SpaceMembership, SpaceRole
from app.services.spaces import SpaceService


class FakeSpaceRepository:
    def __init__(self) -> None:
        self.spaces: dict[UUID, KnowledgeSpace] = {}
        self.categories: dict[UUID, Category] = {}
        self.links: dict[UUID, ShareLink] = {}
        self.roles: dict[tuple[UUID, UUID], SpaceRole] = {}

    async def get_space(self, space_id: UUID) -> KnowledgeSpace | None:
        return self.spaces.get(space_id)

    async def add_space(self, space: KnowledgeSpace) -> None:
        self.spaces[space.id] = space

    async def update_space(self, space: KnowledgeSpace) -> None:
        self.spaces[space.id] = space

    async def add_category(self, category: Category) -> None:
        self.categories[category.id] = category

    async def get_category(self, category_id: UUID) -> Category | None:
        return self.categories.get(category_id)

    async def update_category(self, category: Category) -> None:
        self.categories[category.id] = category

    async def get_categories(
        self, *, space_id: UUID, category_ids: tuple[UUID, ...]
    ) -> list[Category]:
        return [
            category
            for category_id in category_ids
            if (category := self.categories.get(category_id)) is not None
            and category.space_id == space_id
        ]

    async def add_share_link(self, link: ShareLink) -> None:
        self.links[link.id] = link

    async def get_share_link_by_hash(self, token_hash: str) -> ShareLink | None:
        return next(
            (link for link in self.links.values() if link.token_hash == token_hash), None
        )

    async def get_share_link(self, share_link_id: UUID) -> ShareLink | None:
        return self.links.get(share_link_id)

    async def list_share_links(self, space_id: UUID) -> list[ShareLink]:
        return [link for link in self.links.values() if link.space_id == space_id]

    async def update_share_link(self, link: ShareLink) -> None:
        self.links[link.id] = link

    async def revoke_active_links(self, space_id: UUID, revoked_at: datetime) -> None:
        for link_id, link in list(self.links.items()):
            if link.space_id == space_id and link.is_active(at=revoked_at):
                self.links[link_id] = replace(link, status="REVOKED", revoked_at=revoked_at)

    async def add_membership(self, membership: SpaceMembership) -> None:
        self.roles[(membership.space_id, membership.user_id)] = membership.role

    async def get_membership_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        return self.roles.get((space_id, user_id))

    async def clear_category_default(self, *, space_id: UUID, except_category_id: UUID) -> None:
        for category_id, category in list(self.categories.items()):
            if category.space_id == space_id and category_id != except_category_id:
                self.categories[category_id] = replace(category, is_default=False)


def create_service(repository: FakeSpaceRepository) -> SpaceService:
    return SpaceService(
        repository=repository,
        token_pepper="test-only-pepper",
        token_factory=lambda: "only-returned-once-token",
        clock=lambda: datetime(2026, 9, 11, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_categories_can_only_be_created_in_a_public_space() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    private_space = await service.create_space(
        name="私密资料", description=None, visibility=SpaceVisibility.PRIVATE
    )

    with pytest.raises(SpaceRuleViolationError, match="公开空间"):
        await service.create_category(
            space_id=private_space.id,
            name="制度",
            description=None,
            is_open=True,
        )


@pytest.mark.asyncio
async def test_share_link_returns_raw_token_once_but_persists_only_a_hash() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    space = await service.create_space(
        name="公开产品资料", description="供访客问答", visibility=SpaceVisibility.PUBLIC
    )
    category = await service.create_category(
        space_id=space.id,
        name="产品说明",
        description=None,
        is_open=True,
    )

    created = await service.create_share_link(
        space_id=space.id, category_ids=(category.id,)
    )

    assert created.token == "only-returned-once-token"
    assert created.link.token_hash != created.token
    assert len(created.link.token_hash) == 64
    assert repository.links[created.link.id].token_hash == created.link.token_hash
    assert not hasattr(created.link, "token")


@pytest.mark.asyncio
async def test_share_link_normalizes_and_validates_allowed_origins() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    space = await service.create_space(
        name="嵌入公开空间", description=None, visibility=SpaceVisibility.PUBLIC
    )
    category = await service.create_category(
        space_id=space.id, name="开放分类", description=None, is_open=True
    )

    created = await service.create_share_link(
        space_id=space.id,
        category_ids=(category.id,),
        allowed_origins=(" HTTPS://Example.com/ ", "https://example.com", "http://example.com:80"),
    )

    assert created.link.allowed_origins == ("https://example.com", "http://example.com")
    resolved = await service.resolve_public_scope(created.token)
    assert resolved.allowed_origins == created.link.allowed_origins

    await service.revoke_share_link(created.link.id)
    with pytest.raises(SpaceRuleViolationError, match="Origin"):
        await service.create_share_link(
            space_id=space.id,
            category_ids=(category.id,),
            allowed_origins=("https://example.com/embed",),
        )


@pytest.mark.asyncio
async def test_share_link_origin_allowlist_is_bounded() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    space = await service.create_space(
        name="来源限制空间", description=None, visibility=SpaceVisibility.PUBLIC
    )
    category = await service.create_category(
        space_id=space.id, name="开放分类", description=None, is_open=True
    )

    with pytest.raises(SpaceRuleViolationError, match="10"):
        await service.create_share_link(
            space_id=space.id,
            category_ids=(category.id,),
            allowed_origins=tuple(f"https://example-{index}.test" for index in range(11)),
        )


@pytest.mark.asyncio
async def test_closed_or_foreign_categories_cannot_be_added_to_a_share_link() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    public_space = await service.create_space(
        name="公开空间", description=None, visibility=SpaceVisibility.PUBLIC
    )
    closed = await service.create_category(
        space_id=public_space.id,
        name="暂不开放", description=None, is_open=False
    )
    other_space = await service.create_space(
        name="另一个公开空间", description=None, visibility=SpaceVisibility.PUBLIC
    )
    foreign = await service.create_category(
        space_id=other_space.id, name="其他分类", description=None, is_open=True
    )

    with pytest.raises(SpaceRuleViolationError, match="开放"):
        await service.create_share_link(
            space_id=public_space.id, category_ids=(closed.id,)
        )
    with pytest.raises(SpaceRuleViolationError, match="当前空间"):
        await service.create_share_link(
            space_id=public_space.id, category_ids=(foreign.id,)
        )


@pytest.mark.asyncio
async def test_resolved_public_scope_rechecks_category_openness_and_link_revocation() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    space = await service.create_space(
        name="公开空间", description=None, visibility=SpaceVisibility.PUBLIC
    )
    category = await service.create_category(
        space_id=space.id, name="开放分类", description=None, is_open=True
    )
    created = await service.create_share_link(
        space_id=space.id, category_ids=(category.id,)
    )

    scope = await service.resolve_public_scope(created.token)
    assert scope.space_id == space.id
    assert scope.category_ids == (category.id,)
    assert (
        await service.resolve_public_scope_by_link_id(created.link.id)
    ) == scope

    await service.update_category(category.id, is_open=False)
    with pytest.raises(PublicAccessDeniedError):
        await service.resolve_public_scope(created.token)

    await service.update_category(category.id, is_open=True)
    await service.revoke_share_link(created.link.id)
    with pytest.raises(PublicAccessDeniedError):
        await service.resolve_public_scope(created.token)


@pytest.mark.asyncio
async def test_making_a_space_private_revokes_existing_public_links() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    space = await service.create_space(
        name="将关闭的空间", description=None, visibility=SpaceVisibility.PUBLIC
    )
    category = await service.create_category(
        space_id=space.id, name="开放分类", description=None, is_open=True
    )
    created = await service.create_share_link(
        space_id=space.id, category_ids=(category.id,)
    )

    updated = await service.update_space(space.id, visibility=SpaceVisibility.PRIVATE)

    assert updated.visibility is SpaceVisibility.PRIVATE
    assert repository.links[created.link.id].status == "REVOKED"
    with pytest.raises(PublicAccessDeniedError):
        await service.resolve_public_scope(created.token)


@pytest.mark.asyncio
async def test_public_space_keeps_at_most_one_active_share_link() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    space = await service.create_space(
        name="单分享链接空间", description=None, visibility=SpaceVisibility.PUBLIC
    )
    category = await service.create_category(
        space_id=space.id, name="开放分类", description=None, is_open=True
    )
    await service.create_share_link(space_id=space.id, category_ids=(category.id,))

    with pytest.raises(SpaceRuleViolationError, match="一个活动分享链接"):
        await service.create_share_link(space_id=space.id, category_ids=(category.id,))


@pytest.mark.asyncio
async def test_owner_scope_rejects_cross_user_access_without_leaking_space_data() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    owner_id = uuid4()
    other_user_id = uuid4()
    space = await service.create_space(
        name="归属空间",
        description=None,
        visibility=SpaceVisibility.PRIVATE,
        owner_user_id=owner_id,
    )

    assert (await service.get_space(space.id, owner_user_id=owner_id)).id == space.id
    with pytest.raises(SpaceNotFoundError, match="知识空间不存在"):
        await service.get_space(space.id, owner_user_id=other_user_id)


@pytest.mark.asyncio
async def test_public_link_password_and_question_limit_are_enforced() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    space = await service.create_space(
        name="受控公开空间", description=None, visibility=SpaceVisibility.PUBLIC
    )
    category = await service.create_category(
        space_id=space.id, name="展示分类", description=None, is_open=True, is_default=True,
        display_name="对外展示", display_description="访客说明",
    )
    created = await service.create_share_link(
        space_id=space.id,
        category_ids=(category.id,),
        password="pass-1234",
        visitor_question_limit=3,
    )

    with pytest.raises(PublicAccessDeniedError, match="密码错误"):
        await service.resolve_public_scope(created.token, password="wrong")
    scope = await service.resolve_public_scope(created.token, password="pass-1234")
    assert scope.visitor_question_limit == 3
    assert repository.categories[category.id].display_name == "对外展示"


@pytest.mark.asyncio
async def test_member_role_allows_read_but_editor_cannot_change_space_visibility() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    owner_id = uuid4()
    editor_id = uuid4()
    space = await service.create_space(
        name="协作空间",
        description=None,
        visibility=SpaceVisibility.PUBLIC,
        owner_user_id=owner_id,
    )
    repository.roles[(space.id, editor_id)] = SpaceRole.EDITOR

    assert (await service.get_space(space.id, owner_user_id=editor_id)).id == space.id
    with pytest.raises(SpaceAccessDeniedError):
        await service.update_space(
            space.id,
            visibility=SpaceVisibility.PRIVATE,
            owner_user_id=editor_id,
        )

    category = await service.create_category(
        space_id=space.id,
        name="产品",
        description=None,
        is_open=True,
        owner_user_id=editor_id,
    )
    assert category.space_id == space.id


@pytest.mark.asyncio
async def test_owner_can_change_demo_plan_but_editor_cannot() -> None:
    repository = FakeSpaceRepository()
    service = create_service(repository)
    owner_id = uuid4()
    editor_id = uuid4()
    space = await service.create_space(
        name="套餐空间",
        description=None,
        visibility=SpaceVisibility.PRIVATE,
        owner_user_id=owner_id,
    )
    repository.roles[(space.id, editor_id)] = SpaceRole.EDITOR

    upgraded = await service.update_space(
        space.id, plan=SpacePlan.PRO, owner_user_id=owner_id
    )
    assert upgraded.plan is SpacePlan.PRO
    with pytest.raises(SpaceAccessDeniedError):
        await service.update_space(
            space.id, plan=SpacePlan.TEAM, owner_user_id=editor_id
        )
