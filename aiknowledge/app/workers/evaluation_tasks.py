import asyncio
from uuid import UUID

from celery import Celery

from app.core.config import get_settings
from app.infrastructure.database.session import Database


async def process_evaluation_async(run_id: UUID, *, service=None, settings=None) -> str:
    if service is not None:
        result = await service.execute_pending(run_id)
        return result.run.status.value if result is not None else 'SKIPPED'
    settings = settings or get_settings()
    database = Database(url=settings.database_url, pool_size=2, max_overflow=2)
    # Runtime import keeps registration independent from HTTP router imports.
    from app.main import create_app
    app = create_app(settings=settings, database=database)
    try:
        async with database.session() as session:
            evaluator = app.state.evaluation_service_factory(session)
            result = await evaluator.execute_pending(run_id)
            return result.run.status.value if result is not None else 'SKIPPED'
    finally:
        await database.dispose()


async def recover_evaluations_async(*, repository=None, dispatcher=None, settings=None):
    if repository is None:
        settings = settings or get_settings()
        database = Database(url=settings.database_url, pool_size=1, max_overflow=1)
        from app.infrastructure.database.evaluation_repository import SqlAlchemyEvaluationRepository
        from app.infrastructure.queue.evaluation_dispatcher import CeleryEvaluationDispatcher
        from app.workers.celery_app import celery_app
        try:
            async with database.session() as session:
                return await recover_evaluations_async(repository=SqlAlchemyEvaluationRepository(session),
                    dispatcher=CeleryEvaluationDispatcher(celery_app))
        finally:
            await database.dispose()
    runs = await repository.list_recoverable_runs(limit=20)
    counters = {'scanned': len(runs), 'dispatched': 0, 'failed': 0}
    for run_id in runs:
        try:
            await dispatcher.enqueue_evaluation(run_id)
            counters['dispatched'] += 1
        except Exception:
            counters['failed'] += 1
    return counters


def register_evaluation_tasks(celery: Celery):
    recovery_name = 'aiknowledge.evaluations.recover'
    if celery.tasks.get(recovery_name) is None:
        @celery.task(name=recovery_name)
        def recover():
            return asyncio.run(recover_evaluations_async())
    name = 'aiknowledge.evaluations.execute'
    existing = celery.tasks.get(name)
    if existing is not None:
        return existing

    @celery.task(name=name, acks_late=True, reject_on_worker_lost=True)
    def execute(run_id: str):
        return asyncio.run(process_evaluation_async(UUID(run_id)))
    return execute
