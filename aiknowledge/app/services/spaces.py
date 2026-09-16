from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import hmac
from secrets import token_urlsafe
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.spaces import (
    Category,
    CategoryNotFoundError,
    CreatedShareLink,
    KnowledgeSpace,
    PublicAccessDeniedError,
    PublicRetrievalScope,
    ShareLink,
    ShareLinkNotFoundError,
    ShareLinkStatus,
    SpaceNotFoundError,
    SpaceRuleViolationError,
    SpaceVisibility,
)


_UNSET = object()


class SpaceRepository(Protocol):
    async def list_spaces(self) -> list[KnowledgeSpace]: ...

    async def get_space(self, space_id: UUID) -> KnowledgeSpace | None: ...

    async def add_space(self, space: KnowledgeSpace) -> None: ...

    async def update_space(self, space: KnowledgeSpace) -> None: ...

    async def list_categories(self, space_id: UUID) -> list[Category]: ...

    async def add_category(self, category: Category) -> None: ...

    async def get_category(self, category_id: UUID) -> Category | None: ...

    async def update_category(self, category: Category) -> None: ...

    async def list_share_links(self, space_id: UUID) -> list[ShareLink]: ...

    async def get_categories(
        self, *, space_id: UUID, category_ids: tuple[UUID, ...]
    ) -> list[Category]: ...

    async def add_share_link(self, link: ShareLink) -> None: ...

    async def get_share_link(self, share_link_id: UUID) -> ShareLink | None: ...

    async def get_share_link_by_hash(self, token_hash: str) -> ShareLink | None: ...

    async def update_share_link(self, link: ShareLink) -> None: ...

    async def revoke_active_links(self, space_id: UUID, revoked_at: datetime) -> None: ...


class SpaceService:
    """Business rules for the temporary single-workspace owner mode.

    There is deliberately no owner identity in this service yet. Authorization
    is added by the reserved users module later; public access is already
    enforced entirely server-side through a live retrieval scope.
    """

    def __init__(
        self,
        *,
        repository: SpaceRepository,
        token_pepper: str,
        token_factory: Callable[[], str] = lambda: token_urlsafe(32),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not token_pepper:
            raise ValueError("token_pepper must not be empty")
        self._repository = repository
        self._token_pepper = token_pepper.encode("utf-8")
        self._token_factory = token_factory
        self._clock = clock

    async def create_space(
        self,
        *,
        name: str,
        description: str | None,
        visibility: SpaceVisibility,
        guest_feedback_enabled: bool = False,
    ) -> KnowledgeSpace:
        normalized_name = self._normalize_required(name, field="空间名称", maximum=120)
        now = self._now()
        space = KnowledgeSpace(
            id=uuid4(),
            name=normalized_name,
            description=self._normalize_optional(description, maximum=2000),
            visibility=visibility,
            guest_feedback_enabled=guest_feedback_enabled,
            created_at=now,
            updated_at=now,
        )
        await self._repository.add_space(space)
        return space

    async def list_spaces(self) -> list[KnowledgeSpace]:
        return await self._repository.list_spaces()

    async def get_space(self, space_id: UUID) -> KnowledgeSpace:
        return await self._require_space(space_id)

    async def update_space(
        self,
        space_id: UUID,
        *,
        name: str | None = None,
        description: str | None | object = _UNSET,
        visibility: SpaceVisibility | None = None,
        guest_feedback_enabled: bool | None = None,
    ) -> KnowledgeSpace:
        space = await self._require_space(space_id)
        next_visibility = visibility or space.visibility
        now = self._now()
        updated = replace(
            space,
            name=(self._normalize_required(name, field="空间名称", maximum=120) if name is not None else space.name),
            description=(
                self._normalize_optional(description, maximum=2000)
                if description is not _UNSET
                else space.description
            ),
            visibility=next_visibility,
            guest_feedback_enabled=(
                guest_feedback_enabled
                if guest_feedback_enabled is not None
                else space.guest_feedback_enabled
            ),
            updated_at=now,
        )
        await self._repository.update_space(updated)
        if space.visibility == SpaceVisibility.PUBLIC and next_visibility == SpaceVisibility.PRIVATE:
            await self._repository.revoke_active_links(space.id, now)
        return updated

    async def delete_space(self, space_id: UUID) -> KnowledgeSpace:
        space = await self._require_space(space_id)
        now = self._now()
        deleted = replace(space, deleted_at=now, updated_at=now)
        await self._repository.update_space(deleted)
        await self._repository.revoke_active_links(space.id, now)
        return deleted

    async def list_categories(self, space_id: UUID) -> list[Category]:
        await self._require_space(space_id)
        return await self._repository.list_categories(space_id)

    async def create_category(
        self,
        *,
        space_id: UUID,
        name: str,
        description: str | None,
        is_open: bool,
        sort_order: int = 0,
    ) -> Category:
        space = await self._require_space(space_id)
        if space.visibility != SpaceVisibility.PUBLIC:
            raise SpaceRuleViolationError("只有公开空间可以创建分类。")
        now = self._now()
        category = Category(
            id=uuid4(),
            space_id=space_id,
            name=self._normalize_required(name, field="分类名称", maximum=120),
            description=self._normalize_optional(description, maximum=2000),
            is_open=is_open,
            sort_order=sort_order,
            created_at=now,
            updated_at=now,
        )
        await self._repository.add_category(category)
        return category

    async def update_category(
        self,
        category_id: UUID,
        *,
        name: str | None = None,
        description: str | None | object = _UNSET,
        is_open: bool | None = None,
        sort_order: int | None = None,
    ) -> Category:
        category = await self._require_category(category_id)
        await self._require_space(category.space_id)
        updated = replace(
            category,
            name=(self._normalize_required(name, field="分类名称", maximum=120) if name is not None else category.name),
            description=(
                self._normalize_optional(description, maximum=2000)
                if description is not _UNSET
                else category.description
            ),
            is_open=is_open if is_open is not None else category.is_open,
            sort_order=sort_order if sort_order is not None else category.sort_order,
            updated_at=self._now(),
        )
        await self._repository.update_category(updated)
        return updated

    async def delete_category(self, category_id: UUID) -> Category:
        category = await self._require_category(category_id)
        now = self._now()
        deleted = replace(category, is_open=False, deleted_at=now, updated_at=now)
        await self._repository.update_category(deleted)
        return deleted

    async def list_share_links(self, space_id: UUID) -> list[ShareLink]:
        await self._require_space(space_id)
        return await self._repository.list_share_links(space_id)

    async def create_share_link(
        self, *, space_id: UUID, category_ids: Sequence[UUID], expires_at: datetime | None = None
    ) -> CreatedShareLink:
        space = await self._require_space(space_id)
        if space.visibility != SpaceVisibility.PUBLIC:
            raise SpaceRuleViolationError("只有公开空间可以创建分享链接。")
        now = self._now()
        if any(
            link.is_active(at=now)
            for link in await self._repository.list_share_links(space_id)
        ):
            raise SpaceRuleViolationError("每个公开空间最多保留一个活动分享链接。")
        selected_ids = tuple(dict.fromkeys(category_ids))
        if not selected_ids:
            raise SpaceRuleViolationError("分享链接至少需要一个开放分类。")
        categories = await self._repository.get_categories(
            space_id=space_id, category_ids=selected_ids
        )
        if len(categories) != len(selected_ids):
            raise SpaceRuleViolationError("分享链接中的分类必须属于当前空间。")
        if any(not category.is_active or not category.is_open for category in categories):
            raise SpaceRuleViolationError("分享链接只能包含已开放的分类。")
        if expires_at is not None and expires_at <= now:
            raise SpaceRuleViolationError("分享链接的过期时间必须晚于当前时间。")
        raw_token = self._token_factory()
        link = ShareLink(
            id=uuid4(),
            space_id=space_id,
            category_ids=selected_ids,
            token_hash=self._hash_token(raw_token),
            status=ShareLinkStatus.ACTIVE,
            created_at=now,
            expires_at=expires_at,
        )
        await self._repository.add_share_link(link)
        return CreatedShareLink(link=link, token=raw_token)

    async def revoke_share_link(self, share_link_id: UUID) -> ShareLink:
        link = await self._repository.get_share_link(share_link_id)
        if link is None:
            raise ShareLinkNotFoundError("分享链接不存在。")
        if link.status == ShareLinkStatus.REVOKED:
            return link
        revoked = replace(link, status=ShareLinkStatus.REVOKED, revoked_at=self._now())
        await self._repository.update_share_link(revoked)
        return revoked

    async def resolve_public_scope(self, raw_token: str) -> PublicRetrievalScope:
        link = await self._repository.get_share_link_by_hash(self._hash_token(raw_token))
        return await self._resolve_public_link(link)

    async def resolve_public_scope_by_link_id(
        self, share_link_id: UUID
    ) -> PublicRetrievalScope:
        """Resolve a signed visitor session against live link and category state."""

        link = await self._repository.get_share_link(share_link_id)
        return await self._resolve_public_link(link)

    async def _resolve_public_link(
        self, link: ShareLink | None
    ) -> PublicRetrievalScope:
        now = self._now()
        if link is None or not link.is_active(at=now):
            raise PublicAccessDeniedError("分享链接无效、已撤销或已过期。")
        space = await self._repository.get_space(link.space_id)
        if (
            space is None
            or not space.is_active
            or space.visibility != SpaceVisibility.PUBLIC
        ):
            raise PublicAccessDeniedError("公开空间当前不可访问。")
        categories = await self._repository.get_categories(
            space_id=space.id, category_ids=link.category_ids
        )
        category_by_id = {category.id: category for category in categories}
        allowed = tuple(
            category_id
            for category_id in link.category_ids
            if (
                (category := category_by_id.get(category_id)) is not None
                and category.is_active
                and category.is_open
            )
        )
        if not allowed:
            raise PublicAccessDeniedError("分享链接没有可访问的开放分类。")
        return PublicRetrievalScope(
            share_link_id=link.id,
            space_id=space.id,
            category_ids=allowed,
        )

    async def _require_space(self, space_id: UUID) -> KnowledgeSpace:
        space = await self._repository.get_space(space_id)
        if space is None or not space.is_active:
            raise SpaceNotFoundError("知识空间不存在。")
        return space

    async def _require_category(self, category_id: UUID) -> Category:
        category = await self._repository.get_category(category_id)
        if category is None or not category.is_active:
            raise CategoryNotFoundError("分类不存在。")
        return category

    def _hash_token(self, raw_token: str) -> str:
        if not raw_token:
            return ""
        return hmac.new(
            self._token_pepper,
            raw_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _normalize_required(value: str, *, field: str, maximum: int) -> str:
        normalized = value.strip()
        if not normalized:
            raise SpaceRuleViolationError(f"{field}不能为空。")
        if len(normalized) > maximum:
            raise SpaceRuleViolationError(f"{field}不能超过 {maximum} 个字符。")
        return normalized

    @staticmethod
    def _normalize_optional(value: str | None | object, *, maximum: int) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("Optional text must be a string or None.")
        normalized = value.strip()
        if len(normalized) > maximum:
            raise SpaceRuleViolationError(f"描述不能超过 {maximum} 个字符。")
        return normalized or None
