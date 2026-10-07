from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.infrastructure.queue.evaluation_dispatcher import CeleryEvaluationDispatcher
from app.workers.evaluation_tasks import process_evaluation_async, register_evaluation_tasks, recover_evaluations_async
from app.workers.celery_app import create_celery
from app.domain.conversations import EvalRunStatus


@pytest.mark.asyncio
async def test_dispatcher_sends_only_durable_run_id():
    calls = []
    sender = SimpleNamespace(send_task=lambda name, args, kwargs, **options: calls.append((name, args, kwargs, options)))
    run_id = uuid4()
    await CeleryEvaluationDispatcher(sender).enqueue_evaluation(run_id)
    assert calls[0][0] == 'aiknowledge.evaluations.execute'
    assert calls[0][1] == [str(run_id)]
    assert calls[0][2] == {}
    assert calls[0][3]['task_id'] == str(run_id)


@pytest.mark.asyncio
async def test_worker_calls_shared_executor_and_reports_duplicate_as_skipped():
    calls = []
    run_id = uuid4()
    async def execute(value):
        calls.append(value)
        return None
    service = SimpleNamespace(execute_pending=execute)
    assert await process_evaluation_async(run_id, service=service) == 'SKIPPED'
    assert calls == [run_id]


def test_celery_registration_is_idempotent_and_uses_late_ack():
    celery = create_celery(broker_url='memory://', result_backend='cache+memory://')
    first = register_evaluation_tasks(celery)
    second = register_evaluation_tasks(celery)
    assert first is second
    assert first.name == 'aiknowledge.evaluations.execute'
    assert celery.conf.task_acks_late is True


@pytest.mark.asyncio
async def test_recovery_dispatches_durable_ids_without_executing_models_and_continues_after_failure():
    first, second = uuid4(), uuid4()
    calls = []
    async def scan(*, limit):
        assert limit == 20
        return [first, second]
    async def enqueue(run_id):
        calls.append(run_id)
        if run_id == first:
            raise ConnectionError('private broker detail')
    outcome = await recover_evaluations_async(repository=SimpleNamespace(list_recoverable_runs=scan),
        dispatcher=SimpleNamespace(enqueue_evaluation=enqueue))
    assert calls == [first, second]
    assert outcome == {'scanned': 2, 'dispatched': 1, 'failed': 1}
