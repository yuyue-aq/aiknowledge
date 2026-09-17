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
from app.services.evaluations import EvaluationService


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

    async def answer_owner(self, *, space_id: UUID, question: str) -> RagAnswer:
        self.owner_calls.append((space_id, question))
        return RagAnswer(
            status=AnswerStatus.ANSWERED,
            answer="私密空间回答。",
            citations=[Citation(source_chunk_id="chunk-1", title="资料", score=0.9)],
        )

    async def answer_public(
        self, *, space_id: UUID, category_ids: tuple[UUID, ...], question: str
    ) -> RagAnswer:
        self.public_calls.append((space_id, category_ids, question))
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

    detail = await service.run(space_id=repository.space_id)

    assert detail.run.status is EvalRunStatus.COMPLETED
    assert detail.run.retrieval_config_snapshot["chat_model"] == "deepseek-v4-flash"
    assert runner.owner_calls == [(repository.space_id, owner_case.question)]
    assert runner.public_calls == [
        (repository.space_id, (public_category_id,), public_case.question)
    ]
    assert [result.answer_status for result in detail.results] == [
        AnswerStatus.ANSWERED,
        AnswerStatus.INSUFFICIENT_EVIDENCE,
    ]
    assert detail.results[0].citation_count == 1
    # Persist RUNNING before model work so an interrupted run is observable,
    # then atomically persist results and COMPLETED status afterwards.
    assert repository.commits == 4


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
