from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import UUID

from celery import Celery, Task

from app.core.config import Settings, get_settings
from app.infrastructure.database.document_repository import SqlAlchemyDocumentRepository
from app.infrastructure.database.session import Database
from app.infrastructure.embeddings.bge import BgeEmbeddingClient
from app.infrastructure.storage.minio import MinioObjectStorage, ObjectStorageError
from app.services.chunking import TextChunker
from app.services.document_ingestion import DocumentIngestionService
from app.services.document_parsing import DocumentParser
from app.services.document_workflow import DocumentProcessingService, ProcessingOutcome


async def process_document_version_async(
    version_id: UUID,
    *,
    settings: Settings | None = None,
    processor: DocumentProcessingService | None = None,
) -> ProcessingOutcome:
    """Run one document version in the worker process, not the API process."""

    if processor is not None:
        return await processor.process(version_id)

    settings = settings or get_settings()
    database = Database(
        url=settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )
    storage = MinioObjectStorage.from_settings(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key.get_secret_value(),
        bucket_name=settings.minio_bucket,
        secure=settings.minio_secure,
    )
    try:
        async with database.session() as session:
            processing_service = DocumentProcessingService(
                repository=SqlAlchemyDocumentRepository(session),
                storage=storage,
                parser=DocumentParser(),
                ingestion_service=DocumentIngestionService(
                    embedding_client=BgeEmbeddingClient(
                        model_name=settings.bge_model_name,
                        expected_dimension=settings.bge_embedding_dimension,
                        use_fp16=settings.bge_use_fp16,
                        batch_size=settings.bge_batch_size,
                        timeout_seconds=settings.bge_timeout_seconds,
                        max_retries=settings.bge_max_retries,
                    ),
                    chunker=TextChunker(),
                    expected_embedding_dimension=settings.bge_embedding_dimension,
                ),
            )
            return await processing_service.process(version_id)
    finally:
        await database.dispose()


async def cleanup_document_object_async(
    object_key: str,
    *,
    settings: Settings | None = None,
    storage: MinioObjectStorage | None = None,
) -> str:
    """Remove one private object after its document has been soft-deleted."""

    settings = settings or get_settings()
    storage = storage or MinioObjectStorage.from_settings(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key.get_secret_value(),
        bucket_name=settings.minio_bucket,
        secure=settings.minio_secure,
    )
    await storage.delete(object_key)
    return "DELETED"


def register_document_tasks(celery: Celery) -> Task:
    process_task_name = "aiknowledge.documents.process_version"
    process_task = celery.tasks.get(process_task_name)
    if process_task is None:

        @celery.task(
            name=process_task_name,
            autoretry_for=(ObjectStorageError,),
            retry_backoff=True,
            retry_jitter=True,
            retry_kwargs={"max_retries": 3},
        )
        def process_document_version(version_id: str) -> str:
            outcome = asyncio.run(process_document_version_async(UUID(version_id)))
            return outcome.value

        process_task = process_document_version

    cleanup_task_name = "aiknowledge.documents.cleanup_object"
    if celery.tasks.get(cleanup_task_name) is None:

        @celery.task(
            name=cleanup_task_name,
            autoretry_for=(ObjectStorageError,),
            retry_backoff=True,
            retry_jitter=True,
            retry_kwargs={"max_retries": 3},
        )
        def cleanup_document_object(object_key: str) -> str:
            return asyncio.run(cleanup_document_object_async(object_key))

    return process_task
