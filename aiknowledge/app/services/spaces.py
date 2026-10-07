from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import hmac
from secrets import token_urlsafe
from typing import Protocol
from urllib.parse import urlparse
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
    SpaceAccessDeniedError,
    SpaceNotFoundError,
    SpaceRuleViolationError,
    SpacePlan,
    SpaceKind,
    SpaceVisibility,
)
from app.domain.users import SpaceMembership, SpaceRole
from app.services.auth import PasswordService


_UNSET = object()


class SpaceRepository(Protocol):
    async def list_spaces(self, owner_user_id: UUID | None = None) -> list[KnowledgeSpace]: ...

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

    async def add_membership(self, membership: SpaceMembership) -> None: ...

    async def get_membership_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None: ...

    async def clear_category_default(self, *, space_id: UUID, except_category_id: UUID) -> None: ...


class SpaceService:
    """Business rules for spaces, public links and role-aware collaboration."""

    def __init__(
        self,
        *,
        repository: SpaceRepository,
        token_pepper: str,
        token_factory: Callable[[], str] = lambda: token_urlsafe(32),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        password_service: PasswordService | None = None,
    ) -> None:
        if not token_pepper:
            raise ValueError("token_pepper must not be empty")
        self._repository = repository
        self._token_pepper = token_pepper.encode("utf-8")
        self._token_factory = token_factory
        self._clock = clock
        self._passwords = password_service or PasswordService()

    async def create_space(
        self,
        *,
        name: str,
        description: str | None,
        visibility: SpaceVisibility,
        guest_feedback_enabled: bool = False,
        owner_user_id: UUID | None = None,
        kind: SpaceKind = SpaceKind.PERSONAL,
    ) -> KnowledgeSpace:
        normalized_name = self._normalize_required(name, field="空间名称", maximum=120)
        now = self._now()
        space = KnowledgeSpace(
            id=uuid4(),
            owner_user_id=owner_user_id,
            kind=kind,
            plan=SpacePlan.TEAM if kind == SpaceKind.TEAM else SpacePlan.FREE,
            name=normalized_name,
            description=self._normalize_optional(description, maximum=2000),
            visibility=visibility,
            guest_feedback_enabled=guest_feedback_enabled,
            created_at=now,
            updated_at=now,
        )
        await self._repository.add_space(space)
        if owner_user_id is not None:
            await self._repository.add_membership(
                SpaceMembership(
                    space_id=space.id,
                    user_id=owner_user_id,
                    role=SpaceRole.OWNER,
                    created_at=now,
                )
            )
        return space

    async def list_spaces(self, owner_user_id: UUID | None = None) -> list[KnowledgeSpace]:
        return await self._repository.list_spaces(owner_user_id)

    async def get_space(self, space_id: UUID, owner_user_id: UUID | None = None) -> KnowledgeSpace:
        return await self._require_space(space_id, owner_user_id=owner_user_id)

    async def update_space(
        self,
        space_id: UUID,
        *,
        name: str | None = None,
        description: str | None | object = _UNSET,
        visibility: SpaceVisibility | None = None,
        guest_feedback_enabled: bool | None = None,
        plan: SpacePlan | None = None,
        owner_user_id: UUID | None = None,
    ) -> KnowledgeSpace:
        space = await self._require_space(
            space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.OWNER
        )
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
            plan=plan if plan is not None else space.plan,
            updated_at=now,
        )
        await self._repository.update_space(updated)
        if space.visibility == SpaceVisibility.PUBLIC and next_visibility == SpaceVisibility.PRIVATE:
            await self._repository.revoke_active_links(space.id, now)
        return updated

    async def delete_space(self, space_id: UUID, owner_user_id: UUID | None = None) -> KnowledgeSpace:
        space = await self._require_space(
            space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.OWNER
        )
        now = self._now()
        deleted = replace(space, deleted_at=now, updated_at=now)
        await self._repository.update_space(deleted)
        await self._repository.revoke_active_links(space.id, now)
        return deleted

    async def list_categories(self, space_id: UUID, owner_user_id: UUID | None = None) -> list[Category]:
        await self._require_space(space_id, owner_user_id=owner_user_id)
        return await self._repository.list_categories(space_id)

    async def create_category(
        self,
        *,
        space_id: UUID,
        name: str,
        description: str | None,
        is_open: bool,
        sort_order: int = 0,
        owner_user_id: UUID | None = None,
        display_name: str | None = None,
        display_description: str | None = None,
        is_default: bool = False,
    ) -> Category:
        space = await self._require_space(
            space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR
        )
        if space.visibility != SpaceVisibility.PUBLIC:
            raise SpaceRuleViolationError("只有公开空间可以创建分类。")
        now = self._now()
        category = Category(
            id=uuid4(),
            space_id=space_id,
            name=self._normalize_required(name, field="分类名称", maximum=120),
            description=self._normalize_optional(description, maximum=2000),
            display_name=self._normalize_optional(display_name, maximum=120),
            display_description=self._normalize_optional(display_description, maximum=2000),
            is_open=is_open,
            sort_order=sort_order,
            is_default=is_default,
            created_at=now,
            updated_at=now,
        )
        await self._repository.add_category(category)
        if is_default:
            clear_default = getattr(self._repository, "clear_category_default", None)
            if clear_default is not None:
                await clear_default(space_id=space_id, except_category_id=category.id)
        return category

    async def update_category(
        self,
        category_id: UUID,
        *,
        name: str | None = None,
        description: str | None | object = _UNSET,
        is_open: bool | None = None,
        sort_order: int | None = None,
        owner_user_id: UUID | None = None,
        display_name: str | None | object = _UNSET,
        display_description: str | None | object = _UNSET,
        is_default: bool | None = None,
    ) -> Category:
        category = await self._require_category(category_id)
        await self._require_space(
            category.space_id,
            owner_user_id=owner_user_id,
            minimum_role=SpaceRole.EDITOR,
        )
        updated = replace(
            category,
            name=(self._normalize_required(name, field="分类名称", maximum=120) if name is not None else category.name),
            description=(
                self._normalize_optional(description, maximum=2000)
                if description is not _UNSET
                else category.description
            ),
            display_name=(
                self._normalize_optional(display_name, maximum=120)
                if display_name is not _UNSET
                else category.display_name
            ),
            display_description=(
                self._normalize_optional(display_description, maximum=2000)
                if display_description is not _UNSET
                else category.display_description
            ),
            is_open=is_open if is_open is not None else category.is_open,
            sort_order=sort_order if sort_order is not None else category.sort_order,
            is_default=is_default if is_default is not None else category.is_default,
            updated_at=self._now(),
        )
        await self._repository.update_category(updated)
        if updated.is_default:
            clear_default = getattr(self._repository, "clear_category_default", None)
            if clear_default is not None:
                await clear_default(space_id=category.space_id, except_category_id=category.id)
        return updated

    async def delete_category(self, category_id: UUID, owner_user_id: UUID | None = None) -> Category:
        category = await self._require_category(category_id)
        await self._require_space(
            category.space_id,
            owner_user_id=owner_user_id,
            minimum_role=SpaceRole.EDITOR,
        )
        now = self._now()
        deleted = replace(category, is_open=False, deleted_at=now, updated_at=now)
        await self._repository.update_category(deleted)
        return deleted

    async def list_share_links(self, space_id: UUID, owner_user_id: UUID | None = None) -> list[ShareLink]:
        await self._require_space(space_id, owner_user_id=owner_user_id)
        return await self._repository.list_share_links(space_id)

    async def create_share_link(
        self, *, space_id: UUID, category_ids: Sequence[UUID], expires_at: datetime | None = None,
        owner_user_id: UUID | None = None,
        password: str | None = None,
        visitor_question_limit: int | None = None,
        allowed_origins: Sequence[str] | None = None,
    ) -> CreatedShareLink:
        space = await self._require_space(
            space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.OWNER
        )
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
        if visitor_question_limit is not None and not 1 <= visitor_question_limit <= 100_000:
            raise SpaceRuleViolationError("访客提问次数必须在 1 到 100000 之间。")
        if password is not None and (len(password) < 4 or len(password) > 128):
            raise SpaceRuleViolationError("访问密码长度必须在 4 到 128 个字符之间。")
        normalized_origins = _normalize_allowed_origins(allowed_origins)
        raw_token = self._token_factory()
        link = ShareLink(
            id=uuid4(),
            space_id=space_id,
            category_ids=selected_ids,
            token_hash=self._hash_token(raw_token),
            status=ShareLinkStatus.ACTIVE,
            created_at=now,
            expires_at=expires_at,
            password_hash=self._passwords.hash(password) if password else None,
            visitor_question_limit=visitor_question_limit,
            allowed_origins=normalized_origins,
        )
        await self._repository.add_share_link(link)
        return CreatedShareLink(link=link, token=raw_token)

    async def revoke_share_link(self, share_link_id: UUID, owner_user_id: UUID | None = None) -> ShareLink:
        link = await self._repository.get_share_link(share_link_id)
        if link is None:
            raise ShareLinkNotFoundError("分享链接不存在。")
        await self._require_space(
            link.space_id,
            owner_user_id=owner_user_id,
            minimum_role=SpaceRole.OWNER,
        )
        if link.status == ShareLinkStatus.REVOKED:
            return link
        revoked = replace(link, status=ShareLinkStatus.REVOKED, revoked_at=self._now())
        await self._repository.update_share_link(revoked)
        return revoked

    async def resolve_public_scope(self, raw_token: str, password: str | None = None) -> PublicRetrievalScope:
        link = await self._repository.get_share_link_by_hash(self._hash_token(raw_token))
        return await self._resolve_public_link(link, password=password)

    async def resolve_public_scope_by_link_id(
        self, share_link_id: UUID
    ) -> PublicRetrievalScope:
        """Resolve a verified signed visitor session against live state.

        Internal session callers must verify the cookie signature first. The
        password was checked before that cookie was issued; raw-token access
        continues to require a password on every entry.
        """

        link = await self._repository.get_share_link(share_link_id)
        return await self._resolve_public_link(link, password_verified=True)

    async def _resolve_public_link(
        self, link: ShareLink | None, *, password: str | None = None, password_verified: bool = False
    ) -> PublicRetrievalScope:
        now = self._now()
        if link is None or not link.is_active(at=now):
            raise PublicAccessDeniedError("分享链接无效、已撤销或已过期。")
        if not password_verified and link.password_hash is not None and not self._passwords.verify(link.password_hash, password or ""):
            raise PublicAccessDeniedError("分享链接密码错误。")
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
            visitor_question_limit=link.visitor_question_limit,
            allowed_origins=link.allowed_origins,
        )

    async def _require_space(
        self,
        space_id: UUID,
        *,
        owner_user_id: UUID | None = None,
        minimum_role: SpaceRole = SpaceRole.MEMBER,
    ) -> KnowledgeSpace:
        space = await self._repository.get_space(space_id)
        if (
            space is None
            or not space.is_active
            or (
                owner_user_id is not None
                and not await self._has_space_access(
                    space, owner_user_id, minimum_role=minimum_role
                )
            )
        ):
            raise SpaceNotFoundError("知识空间不存在。")
        return space

    async def _has_space_access(
        self,
        space: KnowledgeSpace,
        user_id: UUID,
        *,
        minimum_role: SpaceRole = SpaceRole.MEMBER,
    ) -> bool:
        if space.owner_user_id == user_id:
            return self._role_at_least(SpaceRole.OWNER, minimum_role)
        get_role = getattr(self._repository, "get_membership_role", None)
        if get_role is None:
            return False
        role = await get_role(space_id=space.id, user_id=user_id)
        if role is None:
            return False
        if not self._role_at_least(role, minimum_role):
            raise SpaceAccessDeniedError("你没有执行此操作的空间权限。")
        return True

    @staticmethod
    def _role_at_least(actual: SpaceRole, minimum: SpaceRole) -> bool:
        order = {SpaceRole.MEMBER: 0, SpaceRole.EDITOR: 1, SpaceRole.ADMIN: 2, SpaceRole.OWNER: 3}
        return order[actual] >= order[minimum]

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


def _normalize_allowed_origins(origins: Sequence[str] | None) -> tuple[str, ...]:
    """Normalize and validate browser Origins used by public share embeds.

    Origins intentionally exclude paths, query strings, credentials, and wildcards.
    An empty list means that the share link keeps the normal token/session checks
    without adding an Origin restriction.
    """

    if origins is None:
        return ()
    if len(origins) > 10:
        raise SpaceRuleViolationError("最多配置 10 个允许来源。")
    normalized: list[str] = []
    for raw in origins:
        if not isinstance(raw, str):
            raise SpaceRuleViolationError("允许来源必须是完整的 http/https Origin。")
        value = raw.strip().rstrip("/")
        parsed = urlparse(value)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise SpaceRuleViolationError("允许来源必须是完整的 http/https Origin。")
        try:
            port = parsed.port
        except ValueError as error:
            raise SpaceRuleViolationError("允许来源端口无效。") from error
        host = parsed.hostname.lower()
        default_port = (parsed.scheme.lower() == "http" and port == 80) or (
            parsed.scheme.lower() == "https" and port == 443
        )
        origin = f"{parsed.scheme.lower()}://{host}"
        if port is not None and not default_port:
            origin += f":{port}"
        normalized.append(origin)
    return tuple(dict.fromkeys(normalized))
