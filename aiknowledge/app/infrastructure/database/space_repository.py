from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.spaces import Category, KnowledgeSpace, ShareLink, ShareLinkStatus
from app.domain.users import SpaceMembership, SpaceRole
from app.infrastructure.database.models import (
    CategoryRecord,
    KnowledgeSpaceRecord,
    ShareLinkRecord,
    share_link_categories,
    SpaceMembershipRecord,
)


class SqlAlchemySpaceRepository:
    """PostgreSQL persistence adapter for space and public-link records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_spaces(self, owner_user_id: UUID | None = None) -> list[KnowledgeSpace]:
        query = select(KnowledgeSpaceRecord).where(KnowledgeSpaceRecord.deleted_at.is_(None))
        if owner_user_id is not None:
            query = query.where(
                or_(
                    KnowledgeSpaceRecord.owner_user_id == owner_user_id,
                    exists(
                        select(SpaceMembershipRecord.space_id).where(
                            SpaceMembershipRecord.space_id == KnowledgeSpaceRecord.id,
                            SpaceMembershipRecord.user_id == owner_user_id,
                        )
                    ),
                )
            )
        records = await self._session.scalars(query.order_by(KnowledgeSpaceRecord.updated_at.desc()))
        return [self._to_space(record) for record in records.all()]

    async def get_space(self, space_id: UUID) -> KnowledgeSpace | None:
        record = await self._session.get(KnowledgeSpaceRecord, space_id)
        return self._to_space(record) if record is not None else None

    async def get_membership_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        return await self._session.scalar(
            select(SpaceMembershipRecord.role).where(
                SpaceMembershipRecord.space_id == space_id,
                SpaceMembershipRecord.user_id == user_id,
            )
        )

    async def add_membership(self, membership: SpaceMembership) -> None:
        """Create the owner membership while the space is in the same transaction."""
        self._session.add(
            SpaceMembershipRecord(
                space_id=membership.space_id,
                user_id=membership.user_id,
                role=membership.role,
                created_at=membership.created_at,
            )
        )
        await self._session.flush()

    async def add_space(self, space: KnowledgeSpace) -> None:
        self._session.add(
            KnowledgeSpaceRecord(
                id=space.id,
                owner_user_id=space.owner_user_id,
                name=space.name,
                description=space.description,
                visibility=space.visibility,
                guest_feedback_enabled=space.guest_feedback_enabled,
                plan=space.plan,
                kind=space.kind,
                created_at=space.created_at,
                updated_at=space.updated_at,
                deleted_at=space.deleted_at,
            )
        )
        await self._session.flush()

    async def update_space(self, space: KnowledgeSpace) -> None:
        record = await self._session.get(KnowledgeSpaceRecord, space.id)
        if record is None:
            return
        record.name = space.name
        record.owner_user_id = space.owner_user_id
        record.description = space.description
        record.visibility = space.visibility
        record.guest_feedback_enabled = space.guest_feedback_enabled
        record.plan = space.plan
        record.kind = space.kind
        record.updated_at = space.updated_at
        record.deleted_at = space.deleted_at
        await self._session.flush()

    async def list_categories(self, space_id: UUID) -> list[Category]:
        records = await self._session.scalars(
            select(CategoryRecord)
            .where(
                CategoryRecord.space_id == space_id,
                CategoryRecord.deleted_at.is_(None),
            )
            .order_by(CategoryRecord.sort_order, CategoryRecord.name)
        )
        return [self._to_category(record) for record in records.all()]

    async def add_category(self, category: Category) -> None:
        self._session.add(
            CategoryRecord(
                id=category.id,
                space_id=category.space_id,
                name=category.name,
                description=category.description,
                display_name=category.display_name,
                display_description=category.display_description,
                is_open=category.is_open,
                sort_order=category.sort_order,
                is_default=category.is_default,
                created_at=category.created_at,
                updated_at=category.updated_at,
                deleted_at=category.deleted_at,
            )
        )
        await self._session.flush()

    async def get_category(self, category_id: UUID) -> Category | None:
        record = await self._session.get(CategoryRecord, category_id)
        return self._to_category(record) if record is not None else None

    async def update_category(self, category: Category) -> None:
        record = await self._session.get(CategoryRecord, category.id)
        if record is None:
            return
        record.name = category.name
        record.description = category.description
        record.display_name = category.display_name
        record.display_description = category.display_description
        record.is_open = category.is_open
        record.sort_order = category.sort_order
        record.is_default = category.is_default
        record.updated_at = category.updated_at
        record.deleted_at = category.deleted_at
        await self._session.flush()

    async def clear_category_default(self, *, space_id: UUID, except_category_id: UUID) -> None:
        await self._session.execute(
            update(CategoryRecord)
            .where(
                CategoryRecord.space_id == space_id,
                CategoryRecord.id != except_category_id,
                CategoryRecord.is_default.is_(True),
            )
            .values(is_default=False)
        )
        await self._session.flush()

    async def list_share_links(self, space_id: UUID) -> list[ShareLink]:
        records = await self._session.scalars(
            select(ShareLinkRecord)
            .where(ShareLinkRecord.space_id == space_id)
            .order_by(ShareLinkRecord.created_at.desc())
        )
        return [await self._to_share_link(record) for record in records.all()]

    async def get_categories(
        self, *, space_id: UUID, category_ids: tuple[UUID, ...]
    ) -> list[Category]:
        if not category_ids:
            return []
        result = await self._session.scalars(
            select(CategoryRecord).where(
                CategoryRecord.space_id == space_id,
                CategoryRecord.id.in_(category_ids),
            )
        )
        return [self._to_category(record) for record in result.all()]

    async def add_share_link(self, link: ShareLink) -> None:
        self._session.add(
            ShareLinkRecord(
                id=link.id,
                space_id=link.space_id,
                token_hash=link.token_hash,
                status=link.status,
                created_at=link.created_at,
                revoked_at=link.revoked_at,
                expires_at=link.expires_at,
                password_hash=link.password_hash,
                visitor_question_limit=link.visitor_question_limit,
                allowed_origins=list(link.allowed_origins),
            )
        )
        # The association table has a foreign key to share_links.  Flush the
        # pending parent row before issuing the explicit INSERT, otherwise
        # asyncpg may evaluate the FK before SQLAlchemy has persisted it.
        await self._session.flush()
        await self._session.execute(
            insert(share_link_categories),
            [
                {"share_link_id": link.id, "category_id": category_id}
                for category_id in link.category_ids
            ],
        )

    async def get_share_link(self, share_link_id: UUID) -> ShareLink | None:
        record = await self._session.get(ShareLinkRecord, share_link_id)
        return await self._to_share_link(record) if record is not None else None

    async def get_share_link_by_hash(self, token_hash: str) -> ShareLink | None:
        record = await self._session.scalar(
            select(ShareLinkRecord).where(ShareLinkRecord.token_hash == token_hash)
        )
        return await self._to_share_link(record) if record is not None else None

    async def update_share_link(self, link: ShareLink) -> None:
        record = await self._session.get(ShareLinkRecord, link.id)
        if record is None:
            return
        record.status = link.status
        record.revoked_at = link.revoked_at
        record.expires_at = link.expires_at
        record.password_hash = link.password_hash
        record.visitor_question_limit = link.visitor_question_limit
        record.allowed_origins = list(link.allowed_origins)
        await self._session.flush()

    async def revoke_active_links(self, space_id: UUID, revoked_at: datetime) -> None:
        await self._session.execute(
            update(ShareLinkRecord)
            .where(
                ShareLinkRecord.space_id == space_id,
                ShareLinkRecord.status == ShareLinkStatus.ACTIVE,
            )
            .values(status=ShareLinkStatus.REVOKED, revoked_at=revoked_at)
        )
        await self._session.flush()

    @staticmethod
    def _to_space(record: KnowledgeSpaceRecord) -> KnowledgeSpace:
        return KnowledgeSpace(
            id=record.id,
            owner_user_id=record.owner_user_id,
            name=record.name,
            description=record.description,
            visibility=record.visibility,
            guest_feedback_enabled=record.guest_feedback_enabled,
            plan=record.plan,
            kind=record.kind,
            created_at=record.created_at,
            updated_at=record.updated_at,
            deleted_at=record.deleted_at,
        )

    @staticmethod
    def _to_category(record: CategoryRecord) -> Category:
        return Category(
            id=record.id,
            space_id=record.space_id,
            name=record.name,
            description=record.description,
            display_name=record.display_name,
            display_description=record.display_description,
            is_open=record.is_open,
            sort_order=record.sort_order,
            is_default=record.is_default,
            created_at=record.created_at,
            updated_at=record.updated_at,
            deleted_at=record.deleted_at,
        )

    async def _to_share_link(self, record: ShareLinkRecord) -> ShareLink:
        categories = await self._session.scalars(
            select(share_link_categories.c.category_id)
            .where(share_link_categories.c.share_link_id == record.id)
            .order_by(share_link_categories.c.category_id)
        )
        return ShareLink(
            id=record.id,
            space_id=record.space_id,
            category_ids=tuple(categories.all()),
            token_hash=record.token_hash,
            status=record.status,
            created_at=record.created_at,
            revoked_at=record.revoked_at,
            expires_at=record.expires_at,
            password_hash=record.password_hash,
            visitor_question_limit=record.visitor_question_limit,
            allowed_origins=tuple(record.allowed_origins or ()),
        )
