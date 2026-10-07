from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.conversations import EvalRunStatus, EvalScope
from app.domain.rag import AnswerStatus, RagAnswer
from app.services.evaluations import EvaluationService
from test_evaluation_service import FakeEvaluationRepository, FakeEvaluationRunner


class LeaseRepository(FakeEvaluationRepository):
    def __init__(self):
        super().__init__()
        self.claimed = False
        self.checkpoints = 0
        self.digest = 'same-knowledge'

    async def capture_knowledge_manifest(self, space_id):
        return {'manifest_digest': self.digest, 'document_versions': []}

    async def claim_run(self, run_id, *, lease_token, lease_seconds):
        run = self.runs[run_id]
        if self.claimed or run.status is EvalRunStatus.COMPLETED:
            return None
        self.claimed = True
        run = replace(run, status=EvalRunStatus.RUNNING, lease_owner=lease_token)
        self.runs[run_id] = run
        return run

    async def checkpoint_result(self, result, *, lease_token, lease_seconds):
        run = self.runs[result.eval_run_id]
        if not self.claimed or run.lease_owner != lease_token:
            return False
        if any(x.eval_run_id == result.eval_run_id and x.eval_case_id == result.eval_case_id for x in self.results.values()):
            return True
        self.results[result.id] = result
        self.runs[run.id] = replace(run, progress_completed=run.progress_completed+1)
        self.checkpoints += 1
        return True

    async def finish_run(self, run, *, lease_token):
        if self.runs[run.id].lease_owner != lease_token:
            return False
        self.runs[run.id] = replace(run, lease_owner=None)
        self.claimed = False
        return True

    async def mark_dispatch_failure(self, run_id):
        run = self.runs[run_id]
        if run.status is EvalRunStatus.PENDING:
            self.runs[run_id] = replace(run, failure_code='QUEUE_UNAVAILABLE', failure_message='评测队列暂不可用，可稍后补投此任务。')
        return self.runs[run_id]

    async def prepare_redispatch(self, run_id):
        run = self.runs[run_id]
        if run.status is EvalRunStatus.RUNNING or run.status is EvalRunStatus.COMPLETED:
            return None
        self.runs[run_id] = replace(run, status=EvalRunStatus.PENDING, failure_code=None, failure_message=None)
        return self.runs[run_id]


class Dispatcher:
    def __init__(self, repo, fail=False):
        self.repo, self.fail, self.calls = repo, fail, []

    async def enqueue_evaluation(self, run_id):
        assert self.repo.commits > 0
        assert run_id in self.repo.runs
        self.calls.append(run_id)
        if self.fail:
            raise ConnectionError('broker detail must remain private')


async def setup():
    repo, runner = LeaseRepository(), FakeEvaluationRunner()
    dispatcher = Dispatcher(repo)
    service = EvaluationService(repository=repo, runner=runner, dispatcher=dispatcher,
        run_snapshot={'candidate_limit': 12, 'context_top_k': 4})
    for question in ('第一题', '第二题'):
        await service.create_case(space_id=repo.space_id, question=question, expected_answer='答案',
            expected_document_ids=(), scope=EvalScope.OWNER, category_ids=())
    return service, repo, runner, dispatcher


@pytest.mark.asyncio
async def test_enqueue_freezes_cases_returns_pending_and_calls_no_llm():
    service, repo, runner, dispatcher = await setup()
    run = await service.enqueue_run(space_id=repo.space_id)
    assert run.status is EvalRunStatus.PENDING
    assert (run.progress_completed, run.progress_total) == (0, 2)
    assert len(run.retrieval_config_snapshot['eval_cases']) == 2
    assert dispatcher.calls == [run.id]
    assert runner.owner_calls == []


@pytest.mark.asyncio
async def test_queue_failure_remains_durable_and_recoverable_without_fake_completion():
    service, repo, runner, dispatcher = await setup()
    dispatcher.fail = True
    run = await service.enqueue_run(space_id=repo.space_id)
    assert run.status is EvalRunStatus.PENDING
    assert run.failure_code == 'QUEUE_UNAVAILABLE'
    assert 'broker detail' not in run.failure_message
    assert repo.runs[run.id] == run
    assert runner.owner_calls == []


@pytest.mark.asyncio
async def test_ambiguous_dispatch_failure_does_not_overwrite_claimed_worker():
    service, repo, _, dispatcher = await setup()
    async def ambiguous(run_id):
        await repo.claim_run(run_id, lease_token='already-running', lease_seconds=1200)
        raise ConnectionError('delivery acknowledgement lost')
    dispatcher.enqueue_evaluation = ambiguous
    run = await service.enqueue_run(space_id=repo.space_id)
    assert run.status is EvalRunStatus.RUNNING
    assert repo.runs[run.id].lease_owner == 'already-running'
    assert repo.runs[run.id].failure_code is None


@pytest.mark.asyncio
async def test_retry_failed_run_returns_pending_preserves_snapshot_and_progress():
    service, repo, _, dispatcher = await setup()
    run = await service.enqueue_run(space_id=repo.space_id)
    repo.runs[run.id] = replace(run, status=EvalRunStatus.FAILED, progress_completed=1, failure_code='EVAL_EXECUTION_FAILED')
    retried = await service.redispatch_run(run.id)
    assert retried.status is EvalRunStatus.PENDING
    assert retried.progress_completed == 1
    assert retried.retrieval_config_snapshot == run.retrieval_config_snapshot
    assert retried.failure_code is None
    assert dispatcher.calls == [run.id, run.id]


@pytest.mark.asyncio
async def test_retry_does_not_dispatch_a_live_worker_again():
    service, repo, _, dispatcher = await setup()
    run = await service.enqueue_run(space_id=repo.space_id)
    await repo.claim_run(run.id, lease_token='live', lease_seconds=1200)
    with pytest.raises(ValueError, match='执行中'):
        await service.redispatch_run(run.id)
    assert dispatcher.calls == [run.id]


@pytest.mark.asyncio
async def test_worker_rejects_changed_generation_configuration_before_model_call():
    service, repo, runner, _ = await setup()
    run = await service.enqueue_run(space_id=repo.space_id)
    changed_worker = EvaluationService(repository=repo, runner=runner,
        run_snapshot={'candidate_limit': 12, 'context_top_k': 8})
    outcome = await changed_worker.execute_pending(run.id)
    assert outcome.run.status is EvalRunStatus.FAILED
    assert outcome.run.failure_code == 'EVAL_CONFIG_MISMATCH'
    assert runner.owner_calls == []


@pytest.mark.asyncio
async def test_repeated_delivery_does_not_repeat_completed_model_calls_or_results():
    service, repo, runner, _ = await setup()
    pending = await service.enqueue_run(space_id=repo.space_id)
    first = await service.execute_pending(pending.id)
    second = await service.execute_pending(pending.id)
    assert first.run.status is EvalRunStatus.COMPLETED
    assert second is None
    assert repo.checkpoints == 2
    assert len(runner.owner_calls) == 2
    assert len(repo.results) == 2
    assert repo.runs[pending.id].progress_completed == 2


@pytest.mark.asyncio
async def test_worker_failure_keeps_checkpoint_and_resume_uses_frozen_remaining_cases():
    service, repo, runner, _ = await setup()
    pending = await service.enqueue_run(space_id=repo.space_id)
    original = runner.answer_owner
    async def failing(**kwargs):
        if kwargs['question'] == '第二题':
            raise RuntimeError('private provider failure')
        return await original(**kwargs)
    runner.answer_owner = failing
    first = await service.execute_pending(pending.id)
    assert first.run.status is EvalRunStatus.FAILED
    assert first.run.progress_completed == 1
    assert 'private provider' not in first.run.failure_message
    for case_id, case in list(repo.cases.items()):
        repo.cases[case_id] = replace(case, question='不应进入冻结运行的新问题')
    runner.answer_owner = original
    completed = await service.execute_pending(pending.id)
    assert completed.run.status is EvalRunStatus.COMPLETED
    assert [q for _, q in runner.owner_calls] == ['第一题', '第二题']
    assert repo.checkpoints == 2


@pytest.mark.asyncio
async def test_changed_manifest_aborts_run_before_any_generation():
    service, repo, runner, _ = await setup()
    pending = await service.enqueue_run(space_id=repo.space_id)
    repo.digest = 'changed-knowledge'
    result = await service.execute_pending(pending.id)
    assert result.run.status is EvalRunStatus.FAILED
    assert result.run.failure_code == 'EVAL_SNAPSHOT_INVALID'
    assert not runner.owner_calls


@pytest.mark.asyncio
async def test_manifest_change_during_generation_discards_stale_result():
    service, repo, runner, _ = await setup()
    pending = await service.enqueue_run(space_id=repo.space_id)
    original = runner.answer_owner
    async def changed(**kwargs):
        answer = await original(**kwargs)
        repo.digest = 'changed-during-llm'
        return answer
    runner.answer_owner = changed
    result = await service.execute_pending(pending.id)
    assert result.run.failure_code == 'EVAL_SNAPSHOT_INVALID'
    assert not repo.results


@pytest.mark.asyncio
async def test_lease_loss_prevents_checkpoint_and_terminal_state_write():
    service, repo, runner, _ = await setup()
    pending = await service.enqueue_run(space_id=repo.space_id)
    async def lost(result, **kwargs):
        repo.runs[pending.id] = replace(repo.runs[pending.id], lease_owner='new-worker')
        return False
    repo.checkpoint_result = lost
    assert await service.execute_pending(pending.id) is None
    assert not repo.results
    assert repo.runs[pending.id].status is EvalRunStatus.RUNNING
    assert repo.runs[pending.id].lease_owner == 'new-worker'
