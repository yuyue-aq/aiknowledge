from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.document_workflow import ProcessingOutcome
from app.workers.document_tasks import cleanup_document_object_async, process_document_version_async


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
