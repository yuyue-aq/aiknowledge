from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID


class CeleryTaskSender(Protocol):
    def send_task(self, name: str, args: list[str], kwargs: dict[str, object]) -> object: ...


class CeleryDocumentDispatcher:
    """Keep Celery transport details out of the document application service."""

    task_name = "aiknowledge.documents.process_version"
    cleanup_task_name = "aiknowledge.documents.cleanup_object"

    def __init__(self, celery: CeleryTaskSender) -> None:
        self._celery = celery

    async def enqueue_processing(self, version_id: UUID) -> None:
        await asyncio.to_thread(
            self._celery.send_task,
            self.task_name,
            [str(version_id)],
            {},
        )

    async def enqueue_cleanup(self, object_key: str) -> None:
        """Delete a soft-deleted document object outside the API request."""

        await asyncio.to_thread(
            self._celery.send_task,
            self.cleanup_task_name,
            [object_key],
            {},
        )
