from __future__ import annotations

from celery import Celery, Task


def register_core_tasks(celery: Celery) -> Task:
    """Register the queue smoke-test task on the supplied Celery application."""

    task_name = "aiknowledge.health_check"
    existing = celery.tasks.get(task_name)
    if existing is not None:
        return existing

    @celery.task(name=task_name)
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return health_check
