from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import replace, asdict
from uuid import UUID

from sqlalchemy import exists, or_, select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.documents import (
    DocumentFailureCode,
    DocumentStatus,
    DocumentVersionStatus,
    DocumentVersionConflictError,
    PersistedChunk,
    StoredDocument,
    StoredDocumentVersion,
)
from app.domain.spaces import SpaceVisibility
from app.domain.users import SpaceRole
from app.infrastructure.database.models import (
    CategoryRecord,
    ChunkRecord,
    DocumentRecord,
    DocumentVersionRecord,
    KnowledgeSpaceRecord,
    document_tags,
    SpaceMembershipRecord,
)


class SqlAlchemyDocumentRepository:
    """Persistence adapter for durable document processing and activation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_space_access(self, *, space_id: UUID, user_id: UUID) -> bool:
        space = await self._session.scalar(
            select(KnowledgeSpaceRecord.id).where(
                KnowledgeSpaceRecord.id == space_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
                or_(
                    KnowledgeSpaceRecord.owner_user_id == user_id,
                    exists(
                        select(SpaceMembershipRecord.space_id).where(
                            SpaceMembershipRecord.space_id == KnowledgeSpaceRecord.id,
                            SpaceMembershipRecord.user_id == user_id,
                        )
                    ),
                ),
            )
        )
        return space is not None

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        space = await self._session.scalar(
            select(KnowledgeSpaceRecord).where(
                KnowledgeSpaceRecord.id == space_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
        )
        if space is None:
            return None
        if space.owner_user_id == user_id:
            return SpaceRole.OWNER
        return await self._session.scalar(
            select(SpaceMembershipRecord.role).where(
                SpaceMembershipRecord.space_id == space_id,
                SpaceMembershipRecord.user_id == user_id,
            )
        )

    async def list_documents(self, space_id: UUID) -> list[StoredDocument]:
        records = await self._session.scalars(
            select(DocumentRecord)
            .where(
                DocumentRecord.space_id == space_id,
                DocumentRecord.deleted_at.is_(None),
            )
            .order_by(DocumentRecord.updated_at.desc())
        )
        return [self._to_document(record) for record in records.all()]

    async def search_documents(
        self, space_id: UUID, query: str, tag_id: UUID | None = None
    ) -> list[StoredDocument]:
        pattern = f"%{query}%"
        statement = select(DocumentRecord).where(
            DocumentRecord.space_id == space_id,
            DocumentRecord.deleted_at.is_(None),
            or_(
                DocumentRecord.original_filename.ilike(pattern),
                DocumentRecord.failure_message.ilike(pattern),
            ),
        )
        if tag_id is not None:
            statement = statement.where(
                exists(
                    select(document_tags.c.document_id).where(
                        document_tags.c.document_id == DocumentRecord.id,
                        document_tags.c.tag_id == tag_id,
                    )
                )
            )
        records = await self._session.scalars(
            statement.order_by(DocumentRecord.updated_at.desc())
        )
        return [self._to_document(record) for record in records.all()]

    async def get_document(self, document_id: UUID) -> StoredDocument | None:
        record = await self._session.get(DocumentRecord, document_id)
        return self._to_document(record) if record is not None else None

    async def retry_failed_document(
        self, document_id: UUID
    ) -> tuple[StoredDocument, StoredDocumentVersion] | None:
        document = await self._session.get(
            DocumentRecord, document_id, with_for_update=True
        )
        if document is None or document.status != DocumentStatus.FAILED:
            return None
        version = await self._session.scalar(
            select(DocumentVersionRecord)
            .where(DocumentVersionRecord.document_id == document_id)
            .order_by(DocumentVersionRecord.version_number.desc())
            .with_for_update()
        )
        if version is None or version.status != DocumentVersionStatus.FAILED:
            return None
        now = datetime.now(UTC)
        version.status = DocumentVersionStatus.PROCESSING
        document.status = DocumentStatus.PROCESSING
        document.failure_code = None
        document.failure_message = None
        document.updated_at = now
        await self._session.flush()
        return self._to_document(document), self._to_version(version)

    async def retry_failed_version(self, document_id: UUID, version_id: UUID, *, requested_by_user_id: UUID | None = None) -> tuple[StoredDocument, StoredDocumentVersion] | None:
        document = await self._session.get(DocumentRecord, document_id, with_for_update=True, populate_existing=True)
        if document is None or document.deleted_at is not None or document.status is DocumentStatus.DELETED:
            return None
        version = await self._session.get(DocumentVersionRecord, version_id, with_for_update=True, populate_existing=True)
        if version is None or version.document_id != document_id or version.status is not DocumentVersionStatus.FAILED:
            return None
        if version.chunk_config.get('strategy_version')=='source-paragraph-token-v1':
            from app.domain.documents import DocumentPermissionDeniedError
            role=await self.get_space_role(space_id=document.space_id,user_id=requested_by_user_id) if requested_by_user_id else None
            if role not in (SpaceRole.OWNER,SpaceRole.ADMIN):raise DocumentPermissionDeniedError('你没有重试分块重建的权限。')
            if (version.source_snapshot or {}).get('base_active_version_id')!=str(document.active_version_id):return None
            version.source_snapshot={**(version.source_snapshot or {}),'requested_by_user_id':str(requested_by_user_id)}
        if document.active_version_id is not None and not (version.source_snapshot or {}).get('storage_key'):
            return None
        pending = await self._session.scalar(select(DocumentVersionRecord.id).where(
            DocumentVersionRecord.document_id == document_id, DocumentVersionRecord.status == DocumentVersionStatus.PROCESSING))
        if pending is not None:
            return None
        version.status = DocumentVersionStatus.PROCESSING
        if document.active_version_id is None:
            document.status = DocumentStatus.PROCESSING
            document.failure_code = None
            document.failure_message = None
        document.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._to_document(document), self._to_version(version)

    async def is_valid_document_scope(
        self, *, space_id: UUID, category_id: UUID | None
    ) -> bool:
        space = await self._session.get(KnowledgeSpaceRecord, space_id)
        if space is None or space.deleted_at is not None:
            return False
        if category_id is None:
            return space.visibility == SpaceVisibility.PRIVATE
        category = await self._session.get(CategoryRecord, category_id)
        return bool(
            category is not None
            and category.deleted_at is None
            and category.space_id == space_id
            and space.visibility == SpaceVisibility.PUBLIC
        )

    async def find_active_document_by_hash(
        self, *, space_id: UUID, sha256: str
    ) -> StoredDocument | None:
        record = await self._session.scalar(
            select(DocumentRecord).where(
                DocumentRecord.space_id == space_id,
                DocumentRecord.sha256 == sha256,
                DocumentRecord.deleted_at.is_(None),
                DocumentRecord.status != DocumentStatus.DELETED,
            )
        )
        return self._to_document(record) if record is not None else None

    async def create_processing_document(
        self, document: StoredDocument, version: StoredDocumentVersion
    ) -> None:
        self._session.add(
            DocumentRecord(
                id=document.id,
                space_id=document.space_id,
                owner_user_id=document.owner_user_id,
                category_id=document.category_id,
                original_filename=document.original_filename,
                storage_key=document.storage_key,
                mime_type=document.mime_type,
                size_bytes=document.size_bytes,
                sha256=document.sha256,
                status=document.status,
                active_version_id=document.active_version_id,
                failure_code=document.failure_code,
                failure_message=document.failure_message,
                is_enabled=document.is_enabled,
                effective_at=document.effective_at,
                expires_at=document.expires_at,
                created_at=document.created_at,
                updated_at=document.updated_at,
                deleted_at=document.deleted_at,
            )
        )
        self._session.add(
            DocumentVersionRecord(
                id=version.id,
                document_id=version.document_id,
                version_number=version.version_number,
                parser_version=version.parser_version,
                embedding_provider=version.embedding_provider,
                embedding_model=version.embedding_model,
                embedding_dimension=version.embedding_dimension,
                chunk_config=version.chunk_config,
                source_snapshot=version.source_snapshot,
                status=version.status,
                created_at=version.created_at,
                activated_at=version.activated_at,
            )
        )
        await self._session.flush()

    async def create_replacement_version(self, document: StoredDocument, version: StoredDocumentVersion) -> StoredDocumentVersion:
        current = await self._session.get(DocumentRecord, document.id, with_for_update=True, populate_existing=True)
        if current is None or current.deleted_at is not None or current.active_version_id != document.active_version_id:
            raise DocumentVersionConflictError('资料版本已变化，请刷新后重试。')
        if version.chunk_config.get('strategy_version')=='source-paragraph-token-v1':
            from app.domain.documents import DocumentPermissionDeniedError
            actor=(version.source_snapshot or {}).get('requested_by_user_id')
            role=await self.get_space_role(space_id=document.space_id,user_id=UUID(actor)) if actor else None
            if role not in (SpaceRole.OWNER,SpaceRole.ADMIN):
                raise DocumentPermissionDeniedError('分块重建权限已变化，请重新确认。')
        pending = await self._session.scalar(select(DocumentVersionRecord.id).where(
            DocumentVersionRecord.document_id == document.id, DocumentVersionRecord.status == DocumentVersionStatus.PROCESSING).limit(1))
        if pending is not None:
            raise DocumentVersionConflictError('新版本正在处理中，请等待完成。')
        latest = await self._session.scalar(select(func.max(DocumentVersionRecord.version_number)).where(
            DocumentVersionRecord.document_id == document.id))
        saved = replace(version, version_number=int(latest or 0)+1)
        self._session.add(DocumentVersionRecord(**asdict(saved)))
        await self._session.flush()
        return saved

    async def get_processing_context(
        self, version_id: UUID
    ) -> tuple[StoredDocument, StoredDocumentVersion] | None:
        # Row locks make retries and duplicate Celery deliveries idempotent:
        # a second worker observes the committed terminal version state.
        version = await self._session.get(
            DocumentVersionRecord, version_id, with_for_update=True
        )
        if version is None:
            return None
        document = await self._session.get(
            DocumentRecord, version.document_id, with_for_update=True
        )
        if document is None:
            return None
        stored_document, stored_version = self._to_document(document), self._to_version(version)
        if stored_version.source_snapshot:
            stored_document = replace(stored_document, **{name: stored_version.source_snapshot[name]
                for name in ('storage_key', 'original_filename', 'mime_type', 'size_bytes', 'sha256') if name in stored_version.source_snapshot})
        return stored_document, stored_version

    async def activate_processed_version(
        self, *, version_id: UUID, chunks: tuple[PersistedChunk, ...]
    ) -> bool:
        version = await self._session.get(DocumentVersionRecord, version_id)
        if version is None or version.status != DocumentVersionStatus.PROCESSING:
            return False
        document = await self._session.get(DocumentRecord, version.document_id,with_for_update=True,populate_existing=True)
        version = await self._session.get(DocumentVersionRecord,version_id,with_for_update=True,populate_existing=True)
        if version is None or version.status!=DocumentVersionStatus.PROCESSING:return False
        if document is None or document.status == DocumentStatus.DELETED:
            return False
        if version.chunk_config.get('strategy_version')=='source-paragraph-token-v1' and (version.source_snapshot or {}).get('base_active_version_id')!=str(document.active_version_id):
            raise DocumentVersionConflictError('重建依据的活动版本已变化。')
        await self._session.execute(
            update(ChunkRecord)
            .where(
                ChunkRecord.document_id == document.id,
                ChunkRecord.is_active.is_(True),
            )
            .values(is_active=False)
        )
        for chunk in chunks:
            self._session.add(
                ChunkRecord(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    document_version_id=chunk.document_version_id,
                    space_id=chunk.space_id,
                    category_id=chunk.category_id,
                    ordinal=chunk.ordinal,
                    heading_path=list(chunk.heading_path),
                    page_number=chunk.page_number,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    token_count=chunk.token_count,
                    source_block_id=chunk.source_block_id,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    embedding=chunk.embedding,
                    is_active=True,
                )
            )
        now = datetime.now(UTC)
        version.status = DocumentVersionStatus.READY
        version.activated_at = now
        document.status = DocumentStatus.READY
        if version.source_snapshot:
            for name in ('storage_key', 'original_filename', 'mime_type', 'size_bytes', 'sha256'):
                if name in version.source_snapshot:
                    setattr(document, name, version.source_snapshot[name])
        document.active_version_id = version.id
        document.failure_code = None
        document.failure_message = None
        document.updated_at = now
        await self._session.flush()
        return True

    async def fail_processing_version(
        self, *, version_id: UUID, code: DocumentFailureCode, message: str
    ) -> None:
        version = await self._session.get(DocumentVersionRecord, version_id)
        if version is None or version.status != DocumentVersionStatus.PROCESSING:
            return
        document = await self._session.get(DocumentRecord, version.document_id)
        if document is None or document.status == DocumentStatus.DELETED:
            return
        now = datetime.now(UTC)
        version.status = DocumentVersionStatus.FAILED
        if document.active_version_id is None:
            document.status = DocumentStatus.FAILED
            document.failure_code = code
            document.failure_message = message[:500]
            document.updated_at = now
        await self._session.flush()

    async def mark_document_deleted(self, document_id: UUID) -> None:
        document = await self._session.get(DocumentRecord, document_id, with_for_update=True)
        if document is None or document.status == DocumentStatus.DELETED:
            return
        now = datetime.now(UTC)
        document.status = DocumentStatus.DELETED
        document.deleted_at = now
        document.updated_at = now
        await self._session.execute(
            update(ChunkRecord)
            .where(ChunkRecord.document_id == document_id)
            .values(is_active=False)
        )
        await self._session.flush()

    async def update_document_availability(
        self,
        document_id: UUID,
        *,
        is_enabled: bool | None,
        effective_at: datetime | None,
        expires_at: datetime | None,
    ) -> StoredDocument | None:
        document = await self._session.get(DocumentRecord, document_id, with_for_update=True)
        if document is None or document.deleted_at is not None or document.status == DocumentStatus.DELETED:
            return None
        if is_enabled is not None:
            document.is_enabled = is_enabled
        document.effective_at = effective_at
        document.expires_at = expires_at
        document.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._to_document(document)

    async def list_pending_cleanup(self, limit: int = 20) -> list[tuple[UUID, list[str]]]:
        records = await self._session.scalars(select(DocumentRecord).where(
            DocumentRecord.deleted_at.is_not(None), DocumentRecord.status == DocumentStatus.DELETED,
            DocumentRecord.cleanup_completed_at.is_(None)).order_by(DocumentRecord.deleted_at).limit(max(1, min(limit, 100))))
        pending = []
        for record in records.all():
            versions = await self._session.scalars(select(DocumentVersionRecord).where(DocumentVersionRecord.document_id == record.id))
            keys = [record.storage_key]
            for version in versions.all():
                key = (version.source_snapshot or {}).get('storage_key')
                if isinstance(key, str) and key and key not in keys:
                    keys.append(key)
            pending.append((record.id, keys))
        return pending

    async def mark_cleanup_completed(self, document_id: UUID) -> None:
        record = await self._session.get(DocumentRecord, document_id, with_for_update=True, populate_existing=True)
        if record is not None and record.status is DocumentStatus.DELETED and record.deleted_at is not None:
            record.cleanup_completed_at = datetime.now(UTC)
            await self._session.flush()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def commit(self) -> None:
        await self._session.commit()

    @staticmethod
    def _to_document(record: DocumentRecord) -> StoredDocument:
        return StoredDocument(
            id=record.id,
            space_id=record.space_id,
            owner_user_id=record.owner_user_id,
            category_id=record.category_id,
            original_filename=record.original_filename,
            storage_key=record.storage_key,
            mime_type=record.mime_type,
            size_bytes=record.size_bytes,
            sha256=record.sha256,
            status=record.status,
            active_version_id=record.active_version_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            failure_code=record.failure_code,
            failure_message=record.failure_message,
            is_enabled=record.is_enabled,
            effective_at=record.effective_at,
            expires_at=record.expires_at,
            deleted_at=record.deleted_at,
        )

    @staticmethod
    def _to_version(record: DocumentVersionRecord) -> StoredDocumentVersion:
        return StoredDocumentVersion(
            id=record.id,
            document_id=record.document_id,
            version_number=record.version_number,
            parser_version=record.parser_version,
            embedding_provider=record.embedding_provider,
            embedding_model=record.embedding_model,
            embedding_dimension=record.embedding_dimension,
            chunk_config=dict(record.chunk_config),
            status=record.status,
            created_at=record.created_at,
            activated_at=record.activated_at,
            source_snapshot=dict(record.source_snapshot) if record.source_snapshot else None,
        )
