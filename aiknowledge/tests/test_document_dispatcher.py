from __future__ import annotations

from uuid import uuid4

import pytest

from app.infrastructure.queue.document_dispatcher import CeleryDocumentDispatcher


class FakeCelery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], dict[str, object]]] = []

    def send_task(self, name: str, args: list[str], kwargs: dict[str, object]):
        self.calls.append((name, args, kwargs))


@pytest.mark.asyncio
async def test_document_dispatcher_sends_only_the_version_id_as_the_idempotency_key() -> None:
    celery = FakeCelery()
    dispatcher = CeleryDocumentDispatcher(celery)  # type: ignore[arg-type]
    version_id = uuid4()

    await dispatcher.enqueue_processing(version_id)

    assert celery.calls == [
        (
            "aiknowledge.documents.process_version",
            [str(version_id)],
            {},
        )
    ]


@pytest.mark.asyncio
async def test_document_dispatcher_sends_storage_key_for_async_cleanup() -> None:
    celery = FakeCelery()
    dispatcher = CeleryDocumentDispatcher(celery)  # type: ignore[arg-type]

    await dispatcher.enqueue_cleanup("documents/space/document/source.txt")

    assert celery.calls == [
        (
            "aiknowledge.documents.cleanup_object",
            ["documents/space/document/source.txt"],
            {},
        )
    ]
