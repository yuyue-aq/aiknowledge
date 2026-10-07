from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from app.domain.documents import (
    DocumentBlock,
    DocumentFailureCode,
    DocumentFormat,
    DocumentStatus,
    DocumentVersionStatus,
    ParsedDocument,
)
from app.domain.users import SpaceRole
from app.services.document_ingestion import PreparedChunk, PreparedDocument
from app.services.document_workflow import (
    DocumentAlreadyExistsError,
    DocumentProcessingService,
    DocumentUploadService,
    ProcessingOutcome,
)


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads: list[tuple[str, bytes, str]] = []

    async def put_bytes(self, *, object_key: str, data: bytes, content_type: str, metadata=None):  # type: ignore[no-untyped-def]
        self.objects[object_key] = data
        self.uploads.append((object_key, data, content_type))

    async def get_bytes(self, object_key: str) -> bytes:
        return self.objects[object_key]

    async def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


class FakeRepository:
    def __init__(self) -> None:
        self.valid_scope = True
        self.existing = None
        self.created = None
        self.context = None
        self.activated = None
        self.failed = None
        self.deleted = None
        self.commits = 0

    async def is_valid_document_scope(self, *, space_id: UUID, category_id: UUID | None) -> bool:
        return self.valid_scope

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        return SpaceRole.OWNER

    async def find_active_document_by_hash(self, *, space_id: UUID, sha256: str):  # type: ignore[no-untyped-def]
        return self.existing

    async def create_processing_document(self, document, version):  # type: ignore[no-untyped-def]
        self.created = (document, version)
        self.context = (document, version)

    async def get_processing_context(self, version_id: UUID):  # type: ignore[no-untyped-def]
        return self.context

    async def activate_processed_version(self, *, version_id: UUID, chunks):  # type: ignore[no-untyped-def]
        self.activated = (version_id, chunks)

    async def fail_processing_version(self, *, version_id: UUID, code: DocumentFailureCode, message: str):
        self.failed = (version_id, code, message)
        if self.context is not None:
            document, version = self.context
            self.context = (
                replace(document, status=DocumentStatus.FAILED, failure_code=code, failure_message=message),
                replace(version, status=DocumentVersionStatus.FAILED),
            )

    async def mark_document_deleted(self, document_id: UUID):
        self.deleted = document_id

    async def commit(self) -> None:
        self.commits += 1


class FakeDispatcher:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.enqueued: list[UUID] = []
        self.commit_count_when_enqueued: int | None = None

    async def enqueue_processing(self, version_id: UUID) -> None:
        self.commit_count_when_enqueued = self.repository.commits
        self.enqueued.append(version_id)


class FakeParser:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    def parse(self, *, filename: str, content: bytes) -> ParsedDocument:
        if self.error is not None:
            raise self.error
        return ParsedDocument(
            filename=filename,
            format=DocumentFormat.TEXT,
            blocks=(DocumentBlock(text="可检索资料", heading_path=("说明",), ordinal=1),),
        )


class FakeIngestionService:
    async def prepare(self, document: ParsedDocument) -> PreparedDocument:
        return PreparedDocument(
            chunks=(
                PreparedChunk(
                    ordinal=1,
                    content=document.blocks[0].text,
                    heading_path=document.blocks[0].heading_path,
                    page_number=None,
                    embedding=[0.1, 0.2, 0.3],
                ),
            )
        )


class FailingEmbeddingService:
    async def prepare(self, _document: ParsedDocument) -> PreparedDocument:
        from app.infrastructure.embeddings.bge import EmbeddingBackendUnavailable

        raise EmbeddingBackendUnavailable("BGE backend is unavailable")


def create_upload_service(
    repository: FakeRepository, storage: FakeStorage, dispatcher: FakeDispatcher
) -> DocumentUploadService:
    return DocumentUploadService(
        repository=repository,
        storage=storage,
        dispatcher=dispatcher,
        max_file_bytes=1024,
        embedding_model="BAAI/bge-large-zh-v1.5",
        embedding_dimension=1024,
        key_factory=lambda: uuid4(),
        clock=lambda: datetime(2026, 9, 11, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_broker_failure_leaves_uploaded_document_failed_and_retryable() -> None:
    repository = FakeRepository()
    storage = FakeStorage()

    class UnavailableDispatcher(FakeDispatcher):
        async def enqueue_processing(self, version_id):
            raise ConnectionError("broker unavailable")

    service = create_upload_service(repository, storage, UnavailableDispatcher(repository))
    result = await service.upload(
        space_id=uuid4(), category_id=None, filename="资料.txt",
        content=b"source", content_type="text/plain",
    )
    assert result.processing_enqueued is False
    assert result.document.status is DocumentStatus.FAILED
    assert result.document.failure_code is DocumentFailureCode.QUEUE_UNAVAILABLE
    assert result.version.status is DocumentVersionStatus.FAILED
    assert result.document.storage_key in storage.objects
    assert repository.commits == 2


@pytest.mark.asyncio
async def test_upload_persists_a_processing_version_before_dispatching_an_opaque_storage_key() -> None:
    repository = FakeRepository()
    storage = FakeStorage()
    dispatcher = FakeDispatcher(repository)
    service = create_upload_service(repository, storage, dispatcher)
    space_id = uuid4()

    result = await service.upload(
        space_id=space_id,
        category_id=None,
        filename="产品说明.pdf",
        content=b"%PDF-1.7 small test source",
        content_type="application/pdf",
    )

    document, version = repository.created
    assert document.status is DocumentStatus.PROCESSING
    assert version.status is DocumentVersionStatus.PROCESSING
    assert document.storage_key.startswith(f"documents/{space_id}/")
    assert "产品说明" not in document.storage_key
    assert storage.uploads[0][0] == document.storage_key
    assert dispatcher.enqueued == [version.id]
    assert dispatcher.commit_count_when_enqueued == 1
    assert result.document.id == document.id
    assert result.version.id == version.id
    assert version.chunk_config['token_count_strategy'] == 'model_tokenizer'
    assert version.chunk_config['max_tokens_including_special'] == 512
    assert version.chunk_config['preserve_source_offsets'] is True


@pytest.mark.asyncio
async def test_upload_records_the_document_owner_when_a_user_scope_is_present() -> None:
    repository = FakeRepository()
    storage = FakeStorage()
    dispatcher = FakeDispatcher(repository)
    service = create_upload_service(repository, storage, dispatcher)
    owner_id = uuid4()

    result = await service.upload(
        space_id=uuid4(),
        category_id=None,
        filename="负责人.txt",
        content=b"owned source",
        content_type="text/plain",
        owner_user_id=owner_id,
    )

    assert result.document.owner_user_id == owner_id


@pytest.mark.asyncio
async def test_upload_rejects_duplicate_active_source_without_writing_storage() -> None:
    repository = FakeRepository()
    repository.existing = object()
    storage = FakeStorage()
    dispatcher = FakeDispatcher(repository)
    service = create_upload_service(repository, storage, dispatcher)

    with pytest.raises(DocumentAlreadyExistsError):
        await service.upload(
            space_id=uuid4(),
            category_id=None,
            filename="重复.txt",
            content=b"same source",
            content_type="text/plain",
        )

    assert storage.uploads == []
    assert dispatcher.enqueued == []


@pytest.mark.asyncio
async def test_worker_activates_a_version_only_after_parser_and_embedding_succeed() -> None:
    repository = FakeRepository()
    storage = FakeStorage()
    dispatcher = FakeDispatcher(repository)
    upload = create_upload_service(repository, storage, dispatcher)
    submitted = await upload.upload(
        space_id=uuid4(),
        category_id=None,
        filename="资料.txt",
        content=b"source content",
        content_type="text/plain",
    )
    document, version = repository.created
    repository.context = (document, version)
    processor = DocumentProcessingService(
        repository=repository,
        storage=storage,
        parser=FakeParser(),
        ingestion_service=FakeIngestionService(),
    )

    outcome = await processor.process(submitted.version.id)

    assert outcome is ProcessingOutcome.ACTIVATED
    version_id, chunks = repository.activated
    assert version_id == submitted.version.id
    assert chunks[0].content == "可检索资料"
    assert chunks[0].embedding == [0.1, 0.2, 0.3]
    assert repository.failed is None


@pytest.mark.asyncio
async def test_worker_retains_actual_token_count_and_exact_source_offsets():
    repository, storage = FakeRepository(), FakeStorage()
    submitted = await create_upload_service(repository, storage, FakeDispatcher(repository)).upload(
        space_id=uuid4(), category_id=None, filename='资料.txt', content=b'source', content_type='text/plain')

    class TokenizedIngestion(FakeIngestionService):
        async def prepare(self, document):
            prepared = await super().prepare(document)
            return PreparedDocument(chunks=(replace(prepared.chunks[0], token_count=4,
                source_block_id='block-1', char_start=7, char_end=12),))

    processor = DocumentProcessingService(repository=repository, storage=storage, parser=FakeParser(), ingestion_service=TokenizedIngestion())
    await processor.process(submitted.version.id)
    chunk = repository.activated[1][0]
    assert chunk.token_count == 4
    assert (chunk.source_block_id, chunk.char_start, chunk.char_end) == ('block-1', 7, 12)


@pytest.mark.asyncio
async def test_worker_records_a_parse_failure_without_activating_any_chunk() -> None:
    repository = FakeRepository()
    storage = FakeStorage()
    dispatcher = FakeDispatcher(repository)
    upload = create_upload_service(repository, storage, dispatcher)
    submitted = await upload.upload(
        space_id=uuid4(),
        category_id=None,
        filename="资料.txt",
        content=b"source content",
        content_type="text/plain",
    )
    document, version = repository.created
    repository.context = (document, version)
    from app.services.document_parsing import DocumentParseError

    processor = DocumentProcessingService(
        repository=repository,
        storage=storage,
        parser=FakeParser(
            error=DocumentParseError(DocumentFailureCode.EMPTY_DOCUMENT, "文档内容为空")
        ),
        ingestion_service=FakeIngestionService(),
    )

    outcome = await processor.process(submitted.version.id)

    assert outcome is ProcessingOutcome.FAILED
    assert repository.activated is None
    assert repository.failed == (
        submitted.version.id,
        DocumentFailureCode.EMPTY_DOCUMENT,
        "文档内容为空",
    )
    assert repository.commits >= 2


@pytest.mark.asyncio
async def test_worker_maps_embedding_backend_failure_to_a_retryable_failure_state() -> None:
    repository = FakeRepository()
    storage = FakeStorage()
    dispatcher = FakeDispatcher(repository)
    upload = create_upload_service(repository, storage, dispatcher)
    submitted = await upload.upload(
        space_id=uuid4(),
        category_id=None,
        filename="资料.txt",
        content=b"source content",
        content_type="text/plain",
    )
    document, version = repository.created
    repository.context = (document, version)
    processor = DocumentProcessingService(
        repository=repository,
        storage=storage,
        parser=FakeParser(),
        ingestion_service=FailingEmbeddingService(),
    )

    outcome = await processor.process(submitted.version.id)

    assert outcome is ProcessingOutcome.FAILED
    assert repository.activated is None
    assert repository.failed[1] is DocumentFailureCode.EMBEDDING_FAILED
