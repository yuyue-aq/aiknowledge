from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.conversations import (
    EvalCase,
    EvalResult,
    EvalRun,
    EvalRunStatus,
    EvalScope,
    EvalSetVersion,
)
from app.domain.rag import AnswerStatus, Citation, RagAnswer
from app.domain.retrieval import RetrievalMetadataFilter
from app.services.evaluations import EvaluationService
from app.domain.evaluation import EvidenceRef


@pytest.mark.asyncio
async def test_version_can_freeze_only_selected_cases_and_rejects_foreign_ids():
    service, repo, _ = build_service()
    first = await service.create_case(space_id=repo.space_id, question='调优题', expected_answer='答案',
        expected_document_ids=(), scope=EvalScope.OWNER, category_ids=())
    await service.create_case(space_id=repo.space_id, question='保留题', expected_answer='答案',
        expected_document_ids=(), scope=EvalScope.OWNER, category_ids=())
    version = await service.create_version(space_id=repo.space_id, label='调优集', case_ids=(first.id,))
    assert [item.id for item in version.cases] == [first.id]
    with pytest.raises(ValueError, match='当前空间'):
        await service.create_version(space_id=repo.space_id, label='错误', case_ids=(uuid4(),))
    with pytest.raises(ValueError, match='重复'):
        await service.create_version(space_id=repo.space_id, label='错误', case_ids=(first.id, first.id))


@pytest.mark.asyncio
async def test_case_evidence_survives_version_and_run_snapshots():
    service, repo, _ = build_service()
    evidence = EvidenceRef(uuid4(), uuid4(), 'block-1', 0, 3, 'a'*64)
    async def valid(**kwargs):
        return True
    repo.validate_case_evidence = valid
    question = await service.create_case(space_id=repo.space_id, question='问题', expected_answer='答案',
        expected_document_ids=(evidence.document_id,), scope=EvalScope.OWNER, category_ids=(),
        answerable=True, expected_behavior='ANSWERED', evidence_refs=(evidence,))
    version = await service.create_version(space_id=repo.space_id, label='基线')
    assert version.cases[0].evidence_refs == (evidence,)
    detail = await service.run_version(version.id)
    frozen = (await service.get_run(detail.run.id)).cases_by_id[question.id]
    assert frozen.answerable is True
    assert frozen.expected_behavior == 'ANSWERED'
    assert frozen.evidence_refs == (evidence,)
    updated = await service.update_case(question.id, answerable=False, expected_behavior='INSUFFICIENT_EVIDENCE', evidence_refs=())
    assert updated.answerable is False
    assert updated.evidence_refs == ()
    assert version.cases[0].answerable is True


@pytest.mark.asyncio
async def test_case_rejects_unavailable_or_cross_space_evidence_before_write():
    service, repo, _ = build_service()
    async def invalid(**kwargs):
        return False
    repo.validate_case_evidence = invalid
    with pytest.raises(ValueError):
        await service.create_case(space_id=repo.space_id, question='问题', expected_answer='答案',
            expected_document_ids=(), scope=EvalScope.OWNER, category_ids=(), answerable=True,
            evidence_refs=(EvidenceRef(uuid4(), uuid4(), 'block-1', 0, 2, 'a'*64),))
    assert not repo.cases


@pytest.mark.asyncio
async def test_run_metrics_use_same_execution_candidates_and_known_manifest():
    from app.domain.conversations import RetrievedChunk
    from hashlib import sha256
    service, repo, runner = build_service()
    doc, version = uuid4(), uuid4()
    evidence = EvidenceRef(doc, version, 'block-1', 0, 2, sha256('依据'.encode()).hexdigest())
    async def valid(**kwargs):
        return True
    async def manifest(space_id):
        return {'document_versions': [str(version)], 'manifest_digest': 'known'}
    async def answer(**kwargs):
        hit = RetrievedChunk(uuid4(), doc, '资料', '依据', None, 1, .9, document_version_id=version,
            source_block_id='block-1', char_start=0, char_end=2)
        return RagAnswer(status=AnswerStatus.INSUFFICIENT_EVIDENCE, answer='资料不足',
            execution_snapshot={'retrieved_chunks': [{'chunk_id': str(hit.id)}]}, retrieval_chunks=(hit,))
    repo.validate_case_evidence = valid
    repo.capture_knowledge_manifest = manifest
    runner.answer_owner = answer
    await service.create_case(space_id=repo.space_id, question='问题', expected_answer='答案',
        expected_document_ids=(doc,), scope=EvalScope.OWNER, category_ids=(), answerable=True, evidence_refs=(evidence,))
    detail = await service.run(space_id=repo.space_id)
    assert detail.results[0].citation_count == 0
    assert detail.results[0].retrieval_metrics['document_recall_at_k'] == 1.
    assert detail.results[0].retrieval_metrics['evidence_recall_at_k'] == 1.
    assert detail.results[0].execution_snapshot['retrieved_chunks']


class FakeEvaluationRepository:
    def __init__(self) -> None:
        self.space_id = uuid4()
        self.cases: dict[UUID, EvalCase] = {}
        self.runs: dict[UUID, EvalRun] = {}
        self.results: dict[UUID, EvalResult] = {}
        self.versions: dict[UUID, EvalSetVersion] = {}
        self.commits = 0

    async def has_active_space(self, space_id: UUID) -> bool:
        return space_id == self.space_id

    async def add_case(self, case: EvalCase) -> None:
        self.cases[case.id] = case

    async def list_cases(self, space_id: UUID) -> list[EvalCase]:
        return [case for case in self.cases.values() if case.space_id == space_id]

    async def get_case(self, case_id: UUID) -> EvalCase | None:
        return self.cases.get(case_id)

    async def update_case(self, case: EvalCase) -> None:
        self.cases[case.id] = case

    async def delete_case(self, case_id: UUID) -> None:
        self.cases.pop(case_id, None)

    async def has_results_for_case(self, case_id: UUID) -> bool:
        return any(result.eval_case_id == case_id for result in self.results.values())

    async def add_run(self, run: EvalRun) -> None:
        self.runs[run.id] = run

    async def get_run(self, run_id: UUID) -> EvalRun | None:
        return self.runs.get(run_id)

    async def list_runs(self, space_id: UUID, limit: int = 20) -> list[EvalRun]:
        return [run for run in self.runs.values() if run.space_id == space_id][:limit]

    async def add_version(self, version: EvalSetVersion) -> None:
        self.versions[version.id] = version

    async def list_versions(self, space_id: UUID, limit: int = 20) -> list[EvalSetVersion]:
        return [version for version in self.versions.values() if version.space_id == space_id][:limit]

    async def get_version(self, version_id: UUID) -> EvalSetVersion | None:
        return self.versions.get(version_id)

    async def update_run(self, run: EvalRun) -> None:
        self.runs[run.id] = run

    async def add_result(self, result: EvalResult) -> None:
        self.results[result.id] = result

    async def list_results(self, run_id: UUID) -> list[EvalResult]:
        return [result for result in self.results.values() if result.eval_run_id == run_id]

    async def get_result(self, result_id: UUID) -> EvalResult | None:
        return self.results.get(result_id)

    async def update_result(self, result: EvalResult) -> None:
        self.results[result.id] = result

    async def commit(self) -> None:
        self.commits += 1


class FakeEvaluationRunner:
    def __init__(self) -> None:
        self.owner_calls = []
        self.public_calls = []
        self.metadata_filters = []

    async def answer_owner(self, *, space_id: UUID, question: str, metadata_filter=None) -> RagAnswer:
        self.owner_calls.append((space_id, question))
        self.metadata_filters.append(metadata_filter)
        return RagAnswer(
            status=AnswerStatus.ANSWERED,
            answer="私密空间回答。",
            citations=[Citation(source_chunk_id="chunk-1", title="资料", score=0.9)],
        )

    async def answer_public(
        self, *, space_id: UUID, category_ids: tuple[UUID, ...], question: str, metadata_filter=None
    ) -> RagAnswer:
        self.public_calls.append((space_id, category_ids, question))
        self.metadata_filters.append(metadata_filter)
        return RagAnswer(
            status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            answer="当前资料中没有足够依据回答这个问题。",
        )


def build_service() -> tuple[EvaluationService, FakeEvaluationRepository, FakeEvaluationRunner]:
    repository = FakeEvaluationRepository()
    runner = FakeEvaluationRunner()
    return (
        EvaluationService(
            repository=repository,
            runner=runner,
            run_snapshot={
                "embedding_model": "BAAI/bge-large-zh-v1.5",
                "chat_model": "deepseek-v4-flash",
                "candidate_limit": 12,
                "context_top_k": 4,
            },
            clock=lambda: datetime(2026, 9, 11, tzinfo=UTC),
        ),
        repository,
        runner,
    )


@pytest.mark.asyncio
async def test_evaluation_run_reuses_owner_and_public_answer_paths_and_records_snapshot() -> None:
    service, repository, runner = build_service()
    public_category_id = uuid4()
    owner_case = await service.create_case(
        space_id=repository.space_id,
        question="私密规则是什么？",
        expected_answer="私密空间回答。",
        expected_document_ids=(),
        scope=EvalScope.OWNER,
        category_ids=(),
    )
    public_case = await service.create_case(
        space_id=repository.space_id,
        question="私密规则是什么？",
        expected_answer=None,
        expected_document_ids=(),
        scope=EvalScope.OUT_OF_SCOPE,
        category_ids=(public_category_id,),
    )

    metadata_filter = RetrievalMetadataFilter(formats=("pdf",), version_min=2)
    detail = await service.run(space_id=repository.space_id, metadata_filter=metadata_filter)

    assert detail.run.status is EvalRunStatus.COMPLETED
    assert detail.run.retrieval_config_snapshot["chat_model"] == "deepseek-v4-flash"
    assert detail.run.retrieval_config_snapshot["metadata_filter"] == metadata_filter.snapshot()
    assert runner.metadata_filters == [metadata_filter, metadata_filter]
    assert runner.owner_calls == [(repository.space_id, owner_case.question)]
    assert runner.public_calls == [
        (repository.space_id, (public_category_id,), public_case.question)
    ]
    assert [result.answer_status for result in detail.results] == [
        AnswerStatus.ANSWERED,
        AnswerStatus.INSUFFICIENT_EVIDENCE,
    ]
    assert detail.results[0].citation_count == 1
    # Two case writes, durable PENDING, claim, two per-case checkpoints and
    # terminal state. Model work no longer hides all results until completion.
    assert repository.commits == 7


@pytest.mark.asyncio
async def test_evaluation_case_scope_and_manual_review_are_validated() -> None:
    service, repository, _ = build_service()

    with pytest.raises(ValueError, match="分类"):
        await service.create_case(
            space_id=repository.space_id,
            question="公开问题",
            expected_answer=None,
            expected_document_ids=(),
            scope=EvalScope.PUBLIC,
            category_ids=(),
        )

    case = await service.create_case(
        space_id=repository.space_id,
        question="所有者问题",
        expected_answer=None,
        expected_document_ids=(),
        scope=EvalScope.OWNER,
        category_ids=(),
    )
    detail = await service.run(space_id=repository.space_id)
    reviewed = await service.review_result(
        result_id=detail.results[0].id,
        reviewer_score=0.5,
        reviewer_note="回答部分覆盖。",
    )

    assert case.scope is EvalScope.OWNER
    assert reviewed.reviewer_score == 0.5
    assert reviewed.reviewer_note == "回答部分覆盖。"


@pytest.mark.asyncio
async def test_evaluation_run_history_is_bounded_and_requires_a_valid_limit() -> None:
    service, repository, _ = build_service()
    with pytest.raises(ValueError, match="limit"):
        await service.list_runs(repository.space_id, limit=0)
    with pytest.raises(ValueError, match="limit"):
        await service.list_runs(repository.space_id, limit=51)
    await service.create_case(
        space_id=repository.space_id,
        question="版本问题",
        expected_answer=None,
        expected_document_ids=(),
        scope=EvalScope.OWNER,
        category_ids=(),
    )
    await service.run(space_id=repository.space_id)
    runs = await service.list_runs(repository.space_id, limit=20)
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_evaluation_set_versions_freeze_cases_and_run_snapshot() -> None:
    service, repository, runner = build_service()
    case = await service.create_case(
        space_id=repository.space_id,
        question="当前版本问题",
        expected_answer="预期答案",
        expected_document_ids=(),
        scope=EvalScope.OWNER,
        category_ids=(),
    )
    version = await service.create_version(
        space_id=repository.space_id, label="发布前基线"
    )
    await service.update_case(case.id, question="后来修改的问题")

    assert version.version_number == 1
    assert version.cases[0].question == "当前版本问题"
    detail = await service.run_version(version.id)

    assert detail.run.status is EvalRunStatus.COMPLETED
    assert detail.run.retrieval_config_snapshot["eval_set_version_number"] == 1
    assert runner.owner_calls[-1] == (repository.space_id, "当前版本问题")


@pytest.mark.asyncio
async def test_empty_evaluation_set_cannot_be_versioned() -> None:
    service, repository, _ = build_service()
    with pytest.raises(ValueError, match="至少需要一条"):
        await service.create_version(space_id=repository.space_id, label="空版本")


@pytest.mark.asyncio
async def test_evaluation_runs_can_be_compared_without_reusing_live_case_edits() -> None:
    service, repository, _ = build_service()
    case = await service.create_case(
        space_id=repository.space_id,
        question="版本对比问题",
        expected_answer=None,
        expected_document_ids=(),
        scope=EvalScope.OWNER,
        category_ids=(),
    )
    baseline = await service.run(space_id=repository.space_id)
    await service.review_result(result_id=baseline.results[0].id, reviewer_score=1.0, reviewer_note=None)
    await service.update_case(case.id, question="修改后的版本对比问题")
    candidate = await service.run(space_id=repository.space_id)

    compared = await service.compare_runs(
        baseline_run_id=baseline.run.id,
        candidate_run_id=candidate.run.id,
    )

    assert compared.baseline.run.id == baseline.run.id
    assert compared.candidate.run.id == candidate.run.id
    assert compared.baseline.cases_by_id[case.id].question == "版本对比问题"
    assert compared.candidate.cases_by_id[case.id].question == "修改后的版本对比问题"
    assert compared.same_test_set is False
    assert compared.question_changes[0]['baseline_question'] == '版本对比问题'
    assert compared.question_changes[0]['candidate_question'] == '修改后的版本对比问题'
    assert compared.question_changes[0]['comparable'] is False


@pytest.mark.asyncio
async def test_evaluation_case_with_history_cannot_be_deleted() -> None:
    service, repository, _ = build_service()
    case = await service.create_case(
        space_id=repository.space_id,
        question="保留历史结果的问题",
        expected_answer=None,
        expected_document_ids=(),
        scope=EvalScope.OWNER,
        category_ids=(),
    )
    detail = await service.run(space_id=repository.space_id)

    with pytest.raises(ValueError, match="历史评测结果"):
        await service.delete_case(case.id)

    assert case.id in repository.cases
    assert detail.results[0].id in repository.results


@pytest.mark.asyncio
async def test_explicit_hybrid_eval_snapshot_is_used_by_worker_not_current_default():
    service,repo,runner=build_service()
    received=[]
    async def answer(**kwargs):
        received.append(kwargs)
        return RagAnswer(status=AnswerStatus.INSUFFICIENT_EVIDENCE,answer='无资料')
    runner.answer_owner=answer
    await service.create_case(space_id=repo.space_id,question='固定问题',expected_answer=None,
        expected_document_ids=(),scope=EvalScope.OWNER,category_ids=())
    queued=await service.enqueue_run(space_id=repo.space_id,strategy='hybrid')
    assert queued.retrieval_config_snapshot['retrieval_strategy']=='hybrid'
    detail=await service.execute_pending(queued.id)
    assert detail.run.status is EvalRunStatus.COMPLETED
    assert received[0]['strategy']=='hybrid'
    with pytest.raises(ValueError):await service.enqueue_run(space_id=repo.space_id,strategy='unknown')


@pytest.mark.asyncio
async def test_unused_reranker_configuration_does_not_invalidate_dense_eval():
    service,repo,_=build_service()
    await service.create_case(space_id=repo.space_id,question='固定问题',expected_answer=None,
        expected_document_ids=(),scope=EvalScope.OWNER,category_ids=())
    run=await service.enqueue_run(space_id=repo.space_id)
    service._run_snapshot['reranker_config']={'revision':'new-model'}
    detail=await service.execute_pending(run.id)
    assert detail.run.status is EvalRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_reranker_revision_change_invalidates_only_rerank_eval():
    service,repo,runner=build_service()
    service._run_snapshot['reranker_config']={'revision':'first'}
    await service.create_case(space_id=repo.space_id,question='固定问题',expected_answer=None,
        expected_document_ids=(),scope=EvalScope.OWNER,category_ids=())
    run=await service.enqueue_run(space_id=repo.space_id,strategy='hybrid_rerank')
    service._run_snapshot['reranker_config']={'revision':'second'}
    detail=await service.execute_pending(run.id)
    assert detail.run.status is EvalRunStatus.FAILED and detail.run.failure_code=='EVAL_CONFIG_MISMATCH'
