from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.document_workflow import ProcessingOutcome
from app.workers.document_tasks import cleanup_document_object_async, process_document_version_async


def test_worker_reuses_embedding_client_only_within_same_process_and_configuration(monkeypatch):
    import app.workers.document_tasks as tasks
    from app.core.config import Settings

    built = []
    monkeypatch.setattr(tasks, 'BgeEmbeddingClient', lambda **kwargs: built.append(kwargs) or object())
    monkeypatch.setattr(tasks.os, 'getpid', lambda: 101)
    tasks._worker_embedding_client.cache_clear()
    try:
        settings = Settings(bge_model_name='local-test')
        first = tasks.get_worker_embedding_client(settings)
        assert tasks.get_worker_embedding_client(settings) is first
        assert len(built) == 1
        monkeypatch.setattr(tasks.os, 'getpid', lambda: 102)
        assert tasks.get_worker_embedding_client(settings) is not first
        changed = settings.model_copy(update={'bge_model_name': 'other-local-model'})
        assert tasks.get_worker_embedding_client(changed) is not first
        assert len(built) == 3
    finally:
        tasks._worker_embedding_client.cache_clear()


def test_worker_cached_encoder_works_across_sequential_celery_event_loops(monkeypatch):
    import asyncio
    import app.workers.document_tasks as tasks
    from app.core.config import Settings

    calls = []
    class Model:
        def tokenizer(self, text, **kwargs):
            return {'input_ids': [1, 2]}
        def encode_corpus(self, texts):
            return [[1.0] * 1024 for _ in texts]
    def factory(**kwargs):
        calls.append(kwargs)
        return Model()
    monkeypatch.setattr(tasks.BgeEmbeddingClient, '_default_model_factory', staticmethod(factory))
    tasks._worker_embedding_client.cache_clear()
    try:
        settings = Settings(bge_model_name='sequential-loop-test')
        first = tasks.get_worker_embedding_client(settings)
        assert len(asyncio.run(first.embed_documents(['first']))[0]) == 1024
        second = tasks.get_worker_embedding_client(settings)
        assert len(asyncio.run(second.embed_documents(['second']))[0]) == 1024
        assert len(calls) == 1
    finally:
        tasks._worker_embedding_client.cache_clear()


class FakeProcessor:
    def __init__(self) -> None:
        self.version_id = None

    async def process(self, version_id):  # type: ignore[no-untyped-def]
        self.version_id = version_id
        return ProcessingOutcome.ACTIVATED


@pytest.mark.asyncio
async def test_worker_entry_delegates_only_the_document_version_id_to_processor() -> None:
    processor = FakeProcessor()
    version_id = uuid4()

    result = await process_document_version_async(version_id, processor=processor)  # type: ignore[arg-type]

    assert result is ProcessingOutcome.ACTIVATED
    assert processor.version_id == version_id


class FakeStorage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


@pytest.mark.asyncio
async def test_cleanup_worker_deletes_the_private_object_key() -> None:
    storage = FakeStorage()

    result = await cleanup_document_object_async(
        "documents/space/document/source.txt", storage=storage  # type: ignore[arg-type]
    )

    assert result == "DELETED"
    assert storage.deleted == ["documents/space/document/source.txt"]


@pytest.mark.asyncio
async def test_cleanup_recovery_removes_all_version_sources_and_only_marks_success():
    from app.workers.document_tasks import recover_document_cleanup_async
    first, second = uuid4(), uuid4()
    class Repository:
        completed = []
        async def list_pending_cleanup(self, limit):
            assert limit == 20
            return [(first, ['old', 'new']), (second, ['unavailable'])]
        async def mark_cleanup_completed(self, document_id):
            self.completed.append(document_id)
        async def commit(self): pass
        async def rollback(self): pass
    repository = Repository()
    class Storage(FakeStorage):
        async def delete(self, key):
            if key == 'unavailable': raise RuntimeError('storage unavailable')
            await super().delete(key)
    storage = Storage()
    result = await recover_document_cleanup_async(repository=repository, storage=storage)
    assert result == {'completed': 1, 'failed': 1}
    assert repository.completed == [first]
    assert storage.deleted == ['old', 'new']
