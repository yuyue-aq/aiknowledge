from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.documents import (
    DocumentFailureCode,
    DocumentStatus,
    DocumentVersionStatus,
    PersistedChunk,
    StoredDocument,
    StoredDocumentVersion,
)
from app.domain.spaces import SpaceVisibility
from app.infrastructure.database.models import (
    CategoryRecord,
    ChunkRecord,
    DocumentRecord,
    DocumentVersionRecord,
    KnowledgeSpaceRecord,
)


class SqlAlchemyDocumentRepository:
    """Persistence adapter for durable document processing and activation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
                status=version.status,
                created_at=version.created_at,
                activated_at=version.activated_at,
            )
        )
        await self._session.flush()

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
        return self._to_document(document), self._to_version(version)

    async def activate_processed_version(
        self, *, version_id: UUID, chunks: tuple[PersistedChunk, ...]
    ) -> None:
        version = await self._session.get(DocumentVersionRecord, version_id)
        if version is None or version.status != DocumentVersionStatus.PROCESSING:
            return
        document = await self._session.get(DocumentRecord, version.document_id)
        if document is None or document.status == DocumentStatus.DELETED:
            return
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
                    embedding=chunk.embedding,
                    is_active=True,
                )
            )
        now = datetime.now(UTC)
        version.status = DocumentVersionStatus.READY
        version.activated_at = now
        document.status = DocumentStatus.READY
        document.active_version_id = version.id
        document.failure_code = None
        document.failure_message = None
        document.updated_at = now
        await self._session.flush()

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

    async def commit(self) -> None:
        await self._session.commit()

    @staticmethod
    def _to_document(record: DocumentRecord) -> StoredDocument:
        return StoredDocument(
            id=record.id,
            space_id=record.space_id,
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
        )
