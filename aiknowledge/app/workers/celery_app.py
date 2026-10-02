from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.workers.document_tasks import register_document_tasks
from app.workers.tasks import register_core_tasks
from app.workers.evaluation_tasks import register_evaluation_tasks


def create_celery(*, broker_url: str, result_backend: str) -> Celery:
    """Create an explicitly JSON-only Celery app for background work."""

    celery = Celery(
        "aiknowledge",
        broker=broker_url,
        backend=result_backend,
    )
    celery.conf.update(
        accept_content=["json"],
        broker_connection_retry_on_startup=True,
        result_serializer="json",
        task_acks_late=True,
        task_serializer="json",
        task_track_started=True,
        timezone="UTC",
        beat_schedule={
            'recover-document-cleanup': {'task': 'aiknowledge.documents.recover_cleanup', 'schedule': 60.0},
            'recover-pending-evaluations': {'task': 'aiknowledge.evaluations.recover', 'schedule': 60.0},
        },
    )
    return celery


_settings = get_settings()
celery_app = create_celery(
    broker_url=_settings.redis_url,
    result_backend=_settings.redis_url,
)

# Keep task registration explicit so worker startup cannot accidentally depend
# on route-module imports.
register_core_tasks(celery_app)
register_document_tasks(celery_app)
register_evaluation_tasks(celery_app)
