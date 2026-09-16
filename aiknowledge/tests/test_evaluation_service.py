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
)
from app.domain.rag import AnswerStatus, Citation, RagAnswer
from app.services.evaluations import EvaluationService


class FakeEvaluationRepository:
    def __init__(self) -> None:
        self.space_id = uuid4()
        self.cases: dict[UUID, EvalCase] = {}
        self.runs: dict[UUID, EvalRun] = {}
        self.results: dict[UUID, EvalResult] = {}
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

    async def add_run(self, run: EvalRun) -> None:
        self.runs[run.id] = run

    async def get_run(self, run_id: UUID) -> EvalRun | None:
        return self.runs.get(run_id)

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
