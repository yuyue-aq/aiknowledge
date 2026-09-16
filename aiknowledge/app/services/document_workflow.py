from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
from io import BytesIO
from pathlib import PurePath
from typing import Protocol
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile, is_zipfile

from app.domain.documents import (
    DocumentFailureCode,
    DocumentSubmission,
    DocumentStatus,
    DocumentVersionStatus,
    PersistedChunk,
    StoredDocument,
    StoredDocumentVersion,
)
from app.services.document_ingestion import DocumentIngestionError, PreparedDocument
from app.services.document_parsing import DocumentParseError, DocumentParser
from app.infrastructure.embeddings.bge import EmbeddingBackendUnavailable, EmbeddingDimensionError


class DocumentUploadError(ValueError):
    """A safe validation failure for a file that cannot enter processing."""


class DocumentAlreadyExistsError(ValueError):
    """Raised when an active document has the same source hash in a space."""


class DocumentScopeError(ValueError):
    """Raised when a document does not belong to a valid space/category scope."""


class DocumentRepository(Protocol):
    async def is_valid_document_scope(
        self, *, space_id: UUID, category_id: UUID | None
    ) -> bool: ...

    async def find_active_document_by_hash(
        self, *, space_id: UUID, sha256: str
    ) -> StoredDocument | None: ...

    async def create_processing_document(
        self, document: StoredDocument, version: StoredDocumentVersion
    ) -> None: ...

    async def get_processing_context(
        self, version_id: UUID
    ) -> tuple[StoredDocument, StoredDocumentVersion] | None: ...

    async def activate_processed_version(
        self, *, version_id: UUID, chunks: tuple[PersistedChunk, ...]
    ) -> None: ...

    async def fail_processing_version(
        self, *, version_id: UUID, code: DocumentFailureCode, message: str
    ) -> None: ...

    async def mark_document_deleted(self, document_id: UUID) -> None: ...

    async def commit(self) -> None: ...


class PrivateStorage(Protocol):
    async def put_bytes(
        self, *, object_key: str, data: bytes, content_type: str, metadata: dict[str, str] | None = None
    ) -> object: ...

    async def get_bytes(self, object_key: str) -> bytes: ...

    async def delete(self, object_key: str) -> None: ...


class ProcessingDispatcher(Protocol):
    async def enqueue_processing(self, version_id: UUID) -> None: ...


class IngestionPort(Protocol):
    async def prepare(self, document) -> PreparedDocument: ...  # type: ignore[no-untyped-def]


class ProcessingOutcome(StrEnum):
    ACTIVATED = "ACTIVATED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class DocumentUploadService:
    _CONTENT_TYPES: dict[str, frozenset[str]] = {
        ".pdf": frozenset({"application/pdf"}),
        ".docx": frozenset(
            {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/zip",
            }
        ),
        ".md": frozenset({"text/markdown", "text/plain"}),
        ".markdown": frozenset({"text/markdown", "text/plain"}),
        ".txt": frozenset({"text/plain"}),
    }
    _CANONICAL_MIME: dict[str, str] = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
    }

    def __init__(
        self,
        *,
        repository: DocumentRepository,
        storage: PrivateStorage,
        dispatcher: ProcessingDispatcher,
        max_file_bytes: int,
        embedding_model: str,
        embedding_dimension: int,
        key_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if embedding_dimension <= 0:
            raise ValueError("embedding_dimension must be positive")
        self._repository = repository
        self._storage = storage
        self._dispatcher = dispatcher
        self._max_file_bytes = max_file_bytes
        self._embedding_model = embedding_model
        self._embedding_dimension = embedding_dimension
        self._key_factory = key_factory
        self._clock = clock

    async def upload(
        self,
        *,
        space_id: UUID,
        category_id: UUID | None,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> DocumentSubmission:
        safe_filename, extension, resolved_mime = self._validate_upload(
            filename=filename, content=content, content_type=content_type
        )
        if not await self._repository.is_valid_document_scope(
            space_id=space_id, category_id=category_id
        ):
            raise DocumentScopeError("文档所属的空间或分类不存在。")
        source_hash = hashlib.sha256(content).hexdigest()
        if await self._repository.find_active_document_by_hash(
            space_id=space_id, sha256=source_hash
        ):
            raise DocumentAlreadyExistsError("该空间中已存在相同内容的活动文档。")

        now = self._now()
        document_id = self._key_factory()
        version_id = self._key_factory()
        storage_key = f"documents/{space_id}/{document_id}/source{extension}"
        document = StoredDocument(
            id=document_id,
            space_id=space_id,
            category_id=category_id,
            original_filename=safe_filename,
            storage_key=storage_key,
            mime_type=resolved_mime,
            size_bytes=len(content),
            sha256=source_hash,
            status=DocumentStatus.PROCESSING,
            active_version_id=None,
            created_at=now,
            updated_at=now,
        )
        version = StoredDocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=1,
            parser_version="mvp-parser-v1",
            embedding_provider="local",
            embedding_model=self._embedding_model,
            embedding_dimension=self._embedding_dimension,
            chunk_config={
                "max_characters": 1800,
                "overlap_characters": 240,
                "token_count_strategy": "cjk_character_proxy",
            },
            status=DocumentVersionStatus.PROCESSING,
            created_at=now,
        )
        await self._storage.put_bytes(
            object_key=storage_key,
            data=content,
            content_type=resolved_mime,
            metadata={"sha256": source_hash},
        )
        try:
            await self._repository.create_processing_document(document, version)
            # A worker must never observe a task before its idempotency key is
            # durable in PostgreSQL.
            await self._repository.commit()
        except Exception:
            try:
                await self._storage.delete(storage_key)
            finally:
                raise

        enqueued = True
        try:
            await self._dispatcher.enqueue_processing(version.id)
        except Exception:
            # The persisted PROCESSING state remains retryable through the
            # document API and background recovery; do not claim upload loss.
            enqueued = False
        return DocumentSubmission(
            document=document,
            version=version,
            processing_enqueued=enqueued,
        )

    def _validate_upload(
        self, *, filename: str, content: bytes, content_type: str | None
    ) -> tuple[str, str, str]:
        safe_filename = PurePath(filename.replace("\\", "/")).name.strip()
        extension = PurePath(safe_filename).suffix.lower()
        allowed_content_types = self._CONTENT_TYPES.get(extension)
        if not safe_filename or allowed_content_types is None:
            raise DocumentUploadError("仅支持 PDF、DOCX、Markdown 和 TXT 文件。")
        if len(content) > self._max_file_bytes:
            raise DocumentUploadError("文件超过当前单文件大小上限。")
        normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
        if normalized_content_type and normalized_content_type not in {
            *allowed_content_types,
            "application/octet-stream",
        }:
            raise DocumentUploadError("文件类型与扩展名不匹配。")
        if extension == ".pdf" and content and not content.startswith(b"%PDF-"):
            raise DocumentUploadError("文件内容不是有效的 PDF。")
        if extension == ".docx" and content:
            self._validate_docx_container(content)
        return safe_filename, extension, self._CANONICAL_MIME[extension]

    @staticmethod
    def _validate_docx_container(content: bytes) -> None:
        if not is_zipfile(BytesIO(content)):
            raise DocumentUploadError("文件内容不是有效的 DOCX。")
        try:
            with ZipFile(BytesIO(content)) as archive:
                total_uncompressed = sum(item.file_size for item in archive.infolist())
                if total_uncompressed > 100 * 1024 * 1024 or total_uncompressed > len(content) * 100:
                    raise DocumentUploadError("DOCX 解压后的内容异常大。")
                if "word/document.xml" not in archive.namelist():
                    raise DocumentUploadError("文件内容不是有效的 DOCX。")
        except BadZipFile as exc:
            raise DocumentUploadError("文件内容不是有效的 DOCX。") from exc

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)


class DocumentProcessingService:
    def __init__(
        self,
        *,
        repository: DocumentRepository,
        storage: PrivateStorage,
        parser: DocumentParser,
        ingestion_service: IngestionPort,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._parser = parser
        self._ingestion_service = ingestion_service

    async def process(self, version_id: UUID) -> ProcessingOutcome:
        context = await self._repository.get_processing_context(version_id)
        if context is None:
            return ProcessingOutcome.SKIPPED
        document, version = context
        if (
            document.status == DocumentStatus.DELETED
            or version.status != DocumentVersionStatus.PROCESSING
        ):
            return ProcessingOutcome.SKIPPED
        try:
            source = await self._storage.get_bytes(document.storage_key)
            parsed = self._parser.parse(filename=document.original_filename, content=source)
            prepared = await self._ingestion_service.prepare(parsed)
        except DocumentParseError as error:
            await self._repository.fail_processing_version(
                version_id=version.id, code=error.code, message=str(error)
            )
            await self._repository.commit()
            return ProcessingOutcome.FAILED
        except (
            DocumentIngestionError,
            EmbeddingBackendUnavailable,
            EmbeddingDimensionError,
        ):
            await self._repository.fail_processing_version(
                version_id=version.id,
                code=DocumentFailureCode.EMBEDDING_FAILED,
                message="文档向量化失败，请稍后重试。",
            )
            await self._repository.commit()
            return ProcessingOutcome.FAILED

        chunks = tuple(
            PersistedChunk(
                id=uuid4(),
                document_id=document.id,
                document_version_id=version.id,
                space_id=document.space_id,
                category_id=document.category_id,
                ordinal=chunk.ordinal,
                heading_path=chunk.heading_path,
                page_number=chunk.page_number,
                content=chunk.content,
                content_hash=hashlib.sha256(chunk.content.encode("utf-8")).hexdigest(),
                # The BGE chunker is character-based for CJK text; retaining a
                # conservative proxy makes later evaluation reproducible.
                token_count=max(1, len(chunk.content)),
                embedding=chunk.embedding,
            )
            for chunk in prepared.chunks
        )
        await self._repository.activate_processed_version(version_id=version.id, chunks=chunks)
        await self._repository.commit()
        return ProcessingOutcome.ACTIVATED
