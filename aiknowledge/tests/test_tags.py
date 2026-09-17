from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.tags import KnowledgeTag, TagNameConflictError, TagNotFoundError, TagPermissionDeniedError
from app.domain.users import SpaceRole
from app.services.tags import TagService


class FakeRepository:
    def __init__(self) -> None:
        self.tags: list[KnowledgeTag] = []
        self.assignments: dict[UUID, set[UUID]] = {}
        self.commits = 0
        self.roles: dict[tuple[UUID, UUID], SpaceRole] = {}
        self.document_spaces: dict[UUID, UUID] = {}

    async def list_tags(self, space_id: UUID) -> list[KnowledgeTag]:
        return [tag for tag in self.tags if tag.space_id == space_id]

    async def get_tag(self, tag_id: UUID) -> KnowledgeTag | None:
        return next((tag for tag in self.tags if tag.id == tag_id), None)

    async def find_tag_by_name(self, space_id: UUID, name: str) -> KnowledgeTag | None:
        return next((tag for tag in self.tags if tag.space_id == space_id and tag.name == name), None)

    async def add_tag(self, tag: KnowledgeTag) -> None:
        self.tags.append(tag)

    async def update_tag(self, tag_id: UUID, **changes: object) -> KnowledgeTag | None:
        tag = await self.get_tag(tag_id)
        if tag is None:
            return None
        updated = KnowledgeTag(**{**tag.__dict__, **changes})  # type: ignore[attr-defined]
        self.tags[self.tags.index(tag)] = updated
        return updated

    async def delete_tag(self, tag_id: UUID) -> None:
        self.tags = [tag for tag in self.tags if tag.id != tag_id]
        for assigned in self.assignments.values():
            assigned.discard(tag_id)

    async def set_document_tags(self, document_id: UUID, tag_ids: tuple[UUID, ...]) -> tuple[KnowledgeTag, ...]:
        self.assignments[document_id] = set(tag_ids)
        return tuple(tag for tag in self.tags if tag.id in tag_ids)

    async def get_document_tags(self, document_id: UUID) -> tuple[KnowledgeTag, ...]:
        ids = self.assignments.get(document_id, set())
        return tuple(tag for tag in self.tags if tag.id in ids)

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        return self.roles.get((space_id, user_id))

    async def get_document_space_id(self, document_id: UUID) -> UUID | None:
        return self.document_spaces.get(document_id)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_tag_service_creates_and_assigns_tags() -> None:
    repository = FakeRepository()
    service = TagService(repository=repository, clock=lambda: datetime(2026, 9, 17, tzinfo=UTC))
    space_id = uuid4()
    document_id = uuid4()

    tag = await service.create_tag(space_id=space_id, name=" 产品 ", color="#2F6FED")
    assigned = await service.set_document_tags(
        document_id=document_id,
        tag_ids=(tag.id,),
        space_id=space_id,
    )

    assert tag.name == "产品"
    assert assigned == (tag,)
    assert repository.commits == 2


@pytest.mark.asyncio
async def test_tag_service_rejects_duplicate_and_foreign_tags() -> None:
    repository = FakeRepository()
    service = TagService(repository=repository)
    space_id = uuid4()
    tag = await service.create_tag(space_id=space_id, name="产品")

    with pytest.raises(TagNameConflictError):
        await service.create_tag(space_id=space_id, name="产品")

    with pytest.raises(TagNotFoundError):
        await service.set_document_tags(
            document_id=uuid4(),
            tag_ids=(uuid4(),),
            space_id=space_id,
        )


@pytest.mark.asyncio
async def test_member_can_read_tags_but_only_editor_can_change_them() -> None:
    repository = FakeRepository()
    service = TagService(repository=repository)
    space_id = uuid4()
    member_id = uuid4()
    editor_id = uuid4()
    repository.roles[(space_id, member_id)] = SpaceRole.MEMBER
    repository.roles[(space_id, editor_id)] = SpaceRole.EDITOR

    assert await service.list_tags(space_id, owner_user_id=member_id) == []
    with pytest.raises(TagPermissionDeniedError):
        await service.create_tag(space_id=space_id, name="制度", owner_user_id=member_id)
    tag = await service.create_tag(space_id=space_id, name="制度", owner_user_id=editor_id)
    with pytest.raises(TagPermissionDeniedError):
        await service.delete_tag(tag.id, owner_user_id=member_id)
