from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.tags import (
    KnowledgeTag,
    TagNameConflictError,
    TagPermissionDeniedError,
    TagNotFoundError,
    TagValidationError,
)
from app.domain.users import SpaceRole


class TagRepository(Protocol):
    async def list_tags(self, space_id: UUID) -> list[KnowledgeTag]: ...

    async def get_tag(self, tag_id: UUID) -> KnowledgeTag | None: ...

    async def find_tag_by_name(self, space_id: UUID, name: str) -> KnowledgeTag | None: ...

    async def add_tag(self, tag: KnowledgeTag) -> None: ...

    async def update_tag(self, tag_id: UUID, **changes: object) -> KnowledgeTag | None: ...

    async def delete_tag(self, tag_id: UUID) -> None: ...

    async def set_document_tags(
        self, document_id: UUID, tag_ids: tuple[UUID, ...]
    ) -> tuple[KnowledgeTag, ...]: ...

    async def get_document_tags(self, document_id: UUID) -> tuple[KnowledgeTag, ...]: ...

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None: ...

    async def get_document_space_id(self, document_id: UUID) -> UUID | None: ...

    async def commit(self) -> None: ...


class TagService:
    def __init__(
        self,
        *,
        repository: TagRepository,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory
        self._clock = clock

    async def list_tags(
        self, space_id: UUID, *, owner_user_id: UUID | None = None
    ) -> list[KnowledgeTag]:
        await self._require_role(space_id, owner_user_id, SpaceRole.MEMBER)
        return await self._repository.list_tags(space_id)

    async def create_tag(
        self,
        *,
        space_id: UUID,
        name: str,
        color: str | None = None,
        owner_user_id: UUID | None = None,
    ) -> KnowledgeTag:
        await self._require_role(space_id, owner_user_id, SpaceRole.EDITOR)
        normalized_name = self._normalize_name(name)
        if await self._repository.find_tag_by_name(space_id, normalized_name):
            raise TagNameConflictError("该空间中已经存在同名标签。")
        normalized_color = self._normalize_color(color)
        now = self._now()
        tag = KnowledgeTag(
            id=self._id_factory(),
            space_id=space_id,
            name=normalized_name,
            color=normalized_color,
            created_at=now,
            updated_at=now,
        )
        await self._repository.add_tag(tag)
        await self._repository.commit()
        return tag

    async def update_tag(
        self,
        tag_id: UUID,
        *,
        name: str | None = None,
        color: str | None = None,
        owner_user_id: UUID | None = None,
    ) -> KnowledgeTag:
        current = await self._repository.get_tag(tag_id)
        if current is None:
            raise TagNotFoundError("标签不存在。")
        await self._require_role(current.space_id, owner_user_id, SpaceRole.EDITOR)
        changes: dict[str, object] = {}
        if name is not None:
            normalized_name = self._normalize_name(name)
            existing = await self._repository.find_tag_by_name(current.space_id, normalized_name)
            if existing is not None and existing.id != tag_id:
                raise TagNameConflictError("该空间中已经存在同名标签。")
            changes["name"] = normalized_name
        if color is not None:
            changes["color"] = self._normalize_color(color)
        changes["updated_at"] = self._now()
        updated = await self._repository.update_tag(tag_id, **changes)
        if updated is None:
            raise TagNotFoundError("标签不存在。")
        await self._repository.commit()
        return updated

    async def delete_tag(self, tag_id: UUID, *, owner_user_id: UUID | None = None) -> None:
        current = await self._repository.get_tag(tag_id)
        if current is None:
            raise TagNotFoundError("标签不存在。")
        await self._require_role(current.space_id, owner_user_id, SpaceRole.EDITOR)
        await self._repository.delete_tag(tag_id)
        await self._repository.commit()

    async def get_document_tags(
        self, document_id: UUID, *, owner_user_id: UUID | None = None
    ) -> tuple[KnowledgeTag, ...]:
        if owner_user_id is not None:
            space_id = await self._repository.get_document_space_id(document_id)
            if space_id is None:
                raise TagNotFoundError("文档不存在。")
            await self._require_role(space_id, owner_user_id, SpaceRole.MEMBER)
        return await self._repository.get_document_tags(document_id)

    async def set_document_tags(
        self,
        *,
        document_id: UUID,
        tag_ids: tuple[UUID, ...],
        space_id: UUID,
        owner_user_id: UUID | None = None,
    ) -> tuple[KnowledgeTag, ...]:
        await self._require_role(space_id, owner_user_id, SpaceRole.EDITOR)
        if owner_user_id is not None:
            document_space = await self._repository.get_document_space_id(document_id)
            if document_space != space_id:
                raise TagNotFoundError("文档不存在或不属于当前空间。")
        unique_ids = tuple(dict.fromkeys(tag_ids))
        tags: list[KnowledgeTag] = []
        for tag_id in unique_ids:
            tag = await self._repository.get_tag(tag_id)
            if tag is None or tag.space_id != space_id:
                raise TagNotFoundError("标签不存在或不属于当前空间。")
            tags.append(tag)
        assigned = await self._repository.set_document_tags(document_id, unique_ids)
        await self._repository.commit()
        # Rebuild from the validated set to keep adapters that return no rows
        # deterministic while preserving the caller's requested order.
        return tuple(assigned) if assigned else tuple(tags)

    async def _require_role(
        self, space_id: UUID, user_id: UUID | None, minimum: SpaceRole
    ) -> None:
        if user_id is None:
            return
        reader = getattr(self._repository, "get_space_role", None)
        if reader is None:
            return
        role = await reader(space_id=space_id, user_id=user_id)
        if role is None:
            raise TagNotFoundError("标签不存在。")
        order = {SpaceRole.MEMBER: 0, SpaceRole.EDITOR: 1, SpaceRole.OWNER: 2}
        if order[role] < order[minimum]:
            raise TagPermissionDeniedError("你没有执行此标签操作的权限。")

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = name.strip()
        if not normalized or len(normalized) > 64:
            raise TagValidationError("标签名称不能为空且不能超过 64 个字符。")
        return normalized

    @staticmethod
    def _normalize_color(color: str | None) -> str | None:
        if color is None or not color.strip():
            return None
        normalized = color.strip().upper()
        if len(normalized) not in (4, 7) or not normalized.startswith("#"):
            raise TagValidationError("标签颜色必须是 #RGB 或 #RRGGBB。")
        try:
            int(normalized[1:], 16)
        except ValueError as exc:
            raise TagValidationError("标签颜色必须是 #RGB 或 #RRGGBB。") from exc
        return normalized

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
