from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Sequence
from uuid import UUID, uuid4

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.documents import DocumentStatus
from app.domain.public_answers import (
    PublicAnswer,
    PublicAnswerSourceRef,
    PublicAnswerStatus,
)
from app.domain.spaces import SpaceVisibility
from app.domain.users import SpaceRole
from app.infrastructure.database.models import (
    CategoryRecord,
    DocumentRecord,
    DocumentVersionRecord,
    KnowledgeSpaceRecord,
    PublicAnswerRecord,
    PublicAnswerSourceRecord,
    PublicAnswerVersionRecord,
    SpaceMembershipRecord,
)


class SqlAlchemyPublicAnswerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        space = await self._session.scalar(select(KnowledgeSpaceRecord).where(
            KnowledgeSpaceRecord.id == space_id, KnowledgeSpaceRecord.deleted_at.is_(None)
        ))
        if space is None:
            return None
        if space.owner_user_id == user_id:
            return SpaceRole.OWNER
        return await self._session.scalar(select(SpaceMembershipRecord.role).where(
            SpaceMembershipRecord.space_id == space_id, SpaceMembershipRecord.user_id == user_id
        ))

    async def get_public_answer(self, answer_id: UUID) -> PublicAnswer | None:
        record = await self._session.scalar(select(PublicAnswerRecord).where(
            PublicAnswerRecord.id == answer_id
        ))
        return await self._to_domain(record) if record is not None else None

    async def list_public_answers(self, space_id: UUID) -> list[PublicAnswer]:
        records = await self._session.scalars(select(PublicAnswerRecord).where(
            PublicAnswerRecord.space_id == space_id
        ).order_by(PublicAnswerRecord.updated_at.desc(), PublicAnswerRecord.id))
        return [await self._to_domain(record) for record in records.all()]

    async def add_public_answer(self, answer: PublicAnswer) -> None:
        self._session.add(PublicAnswerRecord(
            id=answer.id,
            space_id=answer.space_id,
            category_id=answer.category_id,
            question=answer.question,
            answer=answer.answer,
            status=answer.status,
            source_refs=[source.to_dict() for source in answer.source_refs],
            created_by=answer.created_by,
            updated_by=answer.updated_by or answer.created_by,
            created_at=answer.created_at,
            updated_at=answer.updated_at,
        ))
        await self._session.flush()

    async def validate_public_answer_draft(self, answer: PublicAnswer) -> bool:
        category_exists = await self._session.scalar(select(exists().where(
            CategoryRecord.id == answer.category_id,
            CategoryRecord.space_id == answer.space_id,
            CategoryRecord.deleted_at.is_(None),
        )))
        if not category_exists:
            return False
        for source in answer.source_refs:
            valid_source = await self._session.scalar(select(DocumentVersionRecord.id).join(
                DocumentRecord, DocumentRecord.id == DocumentVersionRecord.document_id
            ).where(
                DocumentRecord.id == source.document_id,
                DocumentRecord.space_id == answer.space_id,
                DocumentRecord.deleted_at.is_(None),
                DocumentVersionRecord.id == source.document_version_id,
            ).limit(1))
            if not valid_source:
                return False
        return True

    async def update_public_answer(
        self, answer: PublicAnswer, *, revoke_published_reason: str | None = None
    ) -> None:
        record = await self._session.get(PublicAnswerRecord, answer.id, with_for_update=True)
        if record is None:
            return
        if revoke_published_reason is not None:
            await self._session.execute(update(PublicAnswerVersionRecord).where(
                PublicAnswerVersionRecord.answer_id == answer.id,
                PublicAnswerVersionRecord.status == 'PUBLISHED',
            ).values(
                status='WITHDRAWN', withdrawn_at=answer.updated_at,
                withdrawal_reason=revoke_published_reason,
            ))
        record.category_id = answer.category_id
        record.question = answer.question
        record.answer = answer.answer
        record.source_refs = [source.to_dict() for source in answer.source_refs]
        record.status = answer.status.value
        record.updated_by = answer.updated_by or answer.created_by
        record.reviewed_by = answer.reviewed_by
        record.reviewed_at = answer.reviewed_at
        record.withdrawal_reason = answer.withdrawal_reason
        record.updated_at = answer.updated_at
        await self._session.flush()

    async def transition_public_answer(
        self, *, answer_id: UUID, expected_status: Sequence[PublicAnswerStatus],
        status: PublicAnswerStatus, actor_id: UUID, at: datetime,
    ) -> PublicAnswer | None:
        record = await self._session.scalar(select(PublicAnswerRecord).where(
            PublicAnswerRecord.id == answer_id,
            PublicAnswerRecord.status.in_(tuple(expected_status)),
        ).with_for_update())
        if record is None:
            return None
        record.status = status.value
        record.updated_by = actor_id
        record.updated_at = at
        if status is PublicAnswerStatus.IN_REVIEW:
            record.reviewed_by = None
            record.reviewed_at = None
            record.withdrawal_reason = None
        elif status is PublicAnswerStatus.APPROVED:
            record.reviewed_by = actor_id
            record.reviewed_at = at
            record.withdrawal_reason = None
        await self._session.flush()
        return await self._to_domain(record)

    async def validate_public_answer(self, answer: PublicAnswer, *, at: datetime) -> bool:
        category = await self._session.scalar(select(CategoryRecord).join(
            KnowledgeSpaceRecord, KnowledgeSpaceRecord.id == CategoryRecord.space_id
        ).where(
            CategoryRecord.id == answer.category_id,
            CategoryRecord.space_id == answer.space_id,
            CategoryRecord.is_open.is_(True),
            CategoryRecord.deleted_at.is_(None),
            KnowledgeSpaceRecord.deleted_at.is_(None),
            KnowledgeSpaceRecord.visibility == SpaceVisibility.PUBLIC,
        ))
        if category is None:
            return False
        for source in answer.source_refs:
            available = await self._session.scalar(select(DocumentVersionRecord.id).join(
                DocumentRecord, DocumentRecord.id == DocumentVersionRecord.document_id
            ).where(
                DocumentRecord.id == source.document_id,
                DocumentRecord.space_id == answer.space_id,
                DocumentRecord.active_version_id == source.document_version_id,
                DocumentRecord.status == DocumentStatus.READY,
                DocumentRecord.is_enabled.is_(True),
                DocumentRecord.deleted_at.is_(None),
                or_(DocumentRecord.effective_at.is_(None), DocumentRecord.effective_at <= at),
                or_(DocumentRecord.expires_at.is_(None), DocumentRecord.expires_at > at),
                DocumentVersionRecord.id == source.document_version_id,
            ).limit(1))
            if not available:
                return False
        return True

    async def publish_public_answer(
        self, *, answer_id: UUID, actor_id: UUID, embedding: Sequence[float], at: datetime
    ) -> PublicAnswer | None:
        initial = await self._session.scalar(select(PublicAnswerRecord).where(
            PublicAnswerRecord.id == answer_id,
            PublicAnswerRecord.status == PublicAnswerStatus.APPROVED,
        ))
        if initial is None:
            return None
        source_refs_snapshot = list(initial.source_refs or [])
        source_document_ids = sorted({UUID(item['document_id']) for item in source_refs_snapshot})
        if source_document_ids:
            locked_document_ids = await self._session.scalars(select(DocumentRecord.id).where(
                DocumentRecord.id.in_(source_document_ids)
            ).order_by(DocumentRecord.id).with_for_update())
            if set(locked_document_ids.all()) != set(source_document_ids):
                return None
        record = await self._session.scalar(select(PublicAnswerRecord).where(
            PublicAnswerRecord.id == answer_id,
            PublicAnswerRecord.status == PublicAnswerStatus.APPROVED,
        ).with_for_update())
        if record is None or list(record.source_refs or []) != source_refs_snapshot:
            return None
        draft = await self._to_domain(record)
        if not await self.validate_public_answer(draft, at=at):
            return None
        await self._session.execute(update(PublicAnswerVersionRecord).where(
            PublicAnswerVersionRecord.answer_id == answer_id,
            PublicAnswerVersionRecord.status == 'PUBLISHED',
        ).values(status='SUPERSEDED', withdrawn_at=at, withdrawal_reason='REPLACED_BY_NEW_VERSION'))
        last_version = await self._session.scalar(select(func.max(
            PublicAnswerVersionRecord.version_number
        )).where(PublicAnswerVersionRecord.answer_id == answer_id))
        version = PublicAnswerVersionRecord(
            id=uuid4(),
            answer_id=record.id,
            space_id=record.space_id,
            category_id=record.category_id,
            version_number=(last_version or 0) + 1,
            question=record.question,
            answer=record.answer,
            source_count=len(record.source_refs or []),
            content_hash=sha256(f'问题：{record.question}\n答案：{record.answer}'.encode('utf-8')).hexdigest(),
            embedding=list(embedding),
            status='PUBLISHED',
            reviewed_by=record.reviewed_by,
            reviewed_at=record.reviewed_at,
            published_by=actor_id,
            published_at=at,
        )
        self._session.add(version)
        await self._session.flush()
        for source in record.source_refs or []:
            self._session.add(PublicAnswerSourceRecord(
                answer_version_id=version.id,
                document_id=UUID(source['document_id']),
                document_version_id=UUID(source['document_version_id']),
            ))
        record.status = PublicAnswerStatus.PUBLISHED.value
        record.updated_by = actor_id
        record.updated_at = at
        record.withdrawal_reason = None
        await self._session.flush()
        return PublicAnswer(
            id=record.id, space_id=record.space_id, category_id=record.category_id,
            question=record.question, answer=record.answer, status=PublicAnswerStatus(record.status),
            source_refs=tuple(PublicAnswerSourceRef(UUID(item['document_id']), UUID(item['document_version_id']))
                              for item in (record.source_refs or [])),
            created_by=record.created_by or actor_id, created_at=record.created_at,
            updated_at=record.updated_at, updated_by=actor_id, reviewed_by=record.reviewed_by,
            reviewed_at=record.reviewed_at, published_version_id=version.id,
            published_version_number=version.version_number,
        )

    async def withdraw_public_answer(
        self, *, answer_id: UUID, actor_id: UUID, reason: str, at: datetime
    ) -> PublicAnswer | None:
        record = await self._session.scalar(select(PublicAnswerRecord).where(
            PublicAnswerRecord.id == answer_id,
            PublicAnswerRecord.status == PublicAnswerStatus.PUBLISHED,
        ).with_for_update())
        if record is None:
            return None
        await self._session.execute(update(PublicAnswerVersionRecord).where(
            PublicAnswerVersionRecord.answer_id == answer_id,
            PublicAnswerVersionRecord.status == 'PUBLISHED',
        ).values(status='WITHDRAWN', withdrawn_at=at, withdrawal_reason=reason))
        record.status = PublicAnswerStatus.WITHDRAWN.value
        record.withdrawal_reason = reason
        record.updated_by = actor_id
        record.updated_at = at
        await self._session.flush()
        return await self._to_domain(record)

    async def _to_domain(self, record: PublicAnswerRecord) -> PublicAnswer:
        latest = await self._session.scalar(select(PublicAnswerVersionRecord).where(
            PublicAnswerVersionRecord.answer_id == record.id
        ).order_by(PublicAnswerVersionRecord.version_number.desc()).limit(1))
        return PublicAnswer(
            id=record.id,
            space_id=record.space_id,
            category_id=record.category_id,
            question=record.question,
            answer=record.answer,
            status=PublicAnswerStatus(record.status),
            source_refs=tuple(
                PublicAnswerSourceRef(UUID(item['document_id']), UUID(item['document_version_id']))
                for item in (record.source_refs or [])
            ),
            created_by=record.created_by or UUID(int=0),
            created_at=record.created_at,
            updated_at=record.updated_at,
            updated_by=record.updated_by,
            reviewed_by=record.reviewed_by,
            reviewed_at=record.reviewed_at,
            published_version_id=latest.id if latest is not None else None,
            published_version_number=latest.version_number if latest is not None else None,
            withdrawal_reason=record.withdrawal_reason,
        )
