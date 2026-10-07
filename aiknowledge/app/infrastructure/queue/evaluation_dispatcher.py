import asyncio
from uuid import UUID


class CeleryEvaluationDispatcher:
    task_name = 'aiknowledge.evaluations.execute'

    def __init__(self, celery):
        self._celery = celery

    async def enqueue_evaluation(self, run_id: UUID):
        await asyncio.to_thread(self._celery.send_task, self.task_name, [str(run_id)], {}, task_id=str(run_id))
