from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.conversations import (
    EvalCase,
    EvalCaseNotFoundError,
    EvalResult,
    EvalResultNotFoundError,
    EvalRun,
    EvalRunNotFoundError,
    EvalRunStatus,
    EvalScope,
    EvaluationRunDetail,
)
from app.domain.rag import AnswerStatus, RagAnswer


_UNSET = object()


class EvaluationRepository(Protocol):
    async def has_active_space(self, space_id: UUID) -> bool: ...

    async def add_case(self, case: EvalCase) -> None: ...

    async def list_cases(self, space_id: UUID) -> list[EvalCase]: ...

    async def get_case(self, case_id: UUID) -> EvalCase | None: ...

    async def update_case(self, case: EvalCase) -> None: ...

    async def delete_case(self, case_id: UUID) -> None: ...

    async def add_run(self, run: EvalRun) -> None: ...

    async def get_run(self, run_id: UUID) -> EvalRun | None: ...

    async def update_run(self, run: EvalRun) -> None: ...

    async def add_result(self, result: EvalResult) -> None: ...

    async def list_results(self, run_id: UUID) -> list[EvalResult]: ...

    async def get_result(self, result_id: UUID) -> EvalResult | None: ...

    async def update_result(self, result: EvalResult) -> None: ...

    async def commit(self) -> None: ...


class EvaluationAnswerPort(Protocol):
    async def answer_owner(self, *, space_id: UUID, question: str) -> RagAnswer: ...

    async def answer_public(
        self, *, space_id: UUID, category_ids: tuple[UUID, ...], question: str
    ) -> RagAnswer: ...


class EvaluationService:
    """Runs a compact, reproducible test set through formal answer paths."""

    def __init__(
        self,
        *,
        repository: EvaluationRepository,
        runner: EvaluationAnswerPort,
        run_snapshot: dict[str, object],
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._runner = runner
        self._run_snapshot = dict(run_snapshot)
        self._id_factory = id_factory
        self._clock = clock

    async def create_case(
        self,
        *,
        space_id: UUID,
        question: str,
        expected_answer: str | None,
        expected_document_ids: Sequence[UUID],
        scope: EvalScope,
        category_ids: Sequence[UUID],
    ) -> EvalCase:
        await self._require_active_space(space_id)
        case = EvalCase(
            id=self._id_factory(),
            space_id=space_id,
            question=self._normalize_required(question, field="测试问题", maximum=2_000),
            expected_answer=self._normalize_optional(expected_answer, maximum=5_000),
            expected_document_ids=tuple(dict.fromkeys(expected_document_ids)),
            scope=scope,
            category_ids=self._validate_scope_categories(scope, category_ids),
            created_at=self._now(),
        )
        await self._repository.add_case(case)
        await self._repository.commit()
        return case

    async def list_cases(self, space_id: UUID) -> list[EvalCase]:
        await self._require_active_space(space_id)
        return await self._repository.list_cases(space_id)

    async def update_case(
        self,
        case_id: UUID,
        *,
        question: str | None = None,
        expected_answer: str | None | object = _UNSET,
        expected_document_ids: Sequence[UUID] | None = None,
        scope: EvalScope | None = None,
        category_ids: Sequence[UUID] | None = None,
    ) -> EvalCase:
        case = await self._require_case(case_id)
        next_scope = scope or case.scope
        next_categories = self._validate_scope_categories(
            next_scope, category_ids if category_ids is not None else case.category_ids
        )
        updated = replace(
            case,
            question=(
                self._normalize_required(question, field="测试问题", maximum=2_000)
                if question is not None
                else case.question
            ),
            expected_answer=(
                self._normalize_optional(expected_answer, maximum=5_000)
                if expected_answer is not _UNSET
                else case.expected_answer
            ),
            expected_document_ids=(
                tuple(dict.fromkeys(expected_document_ids))
                if expected_document_ids is not None
                else case.expected_document_ids
            ),
            scope=next_scope,
            category_ids=next_categories,
        )
        await self._repository.update_case(updated)
        await self._repository.commit()
        return updated

    async def delete_case(self, case_id: UUID) -> None:
        case = await self._require_case(case_id)
        await self._repository.delete_case(case.id)
        await self._repository.commit()

    async def run(self, *, space_id: UUID) -> EvaluationRunDetail:
        await self._require_active_space(space_id)
        started_at = self._now()
        run = EvalRun(
            id=self._id_factory(),
            space_id=space_id,
            status=EvalRunStatus.RUNNING,
            retrieval_config_snapshot=dict(self._run_snapshot),
            created_at=started_at,
            started_at=started_at,
        )
        await self._repository.add_run(run)
        # A model timeout or process crash must never make the run invisible.
        await self._repository.commit()
        try:
            results: list[EvalResult] = []
            cases = await self._repository.list_cases(space_id)
            for case in cases:
                answer = await self._run_case(case)
                result = EvalResult(
                    id=self._id_factory(),
                    eval_run_id=run.id,
                    eval_case_id=case.id,
                    answer_status=answer.status,
                    answer=answer.answer,
                    citation_count=len(answer.citations),
                )
                await self._repository.add_result(result)
                results.append(result)
            completed = replace(
                run,
                status=EvalRunStatus.COMPLETED,
                completed_at=self._now(),
            )
            await self._repository.update_run(completed)
            await self._repository.commit()
            return EvaluationRunDetail(
                run=completed,
                results=tuple(results),
                cases_by_id={case.id: case for case in cases},
            )
        except Exception:
            failed = replace(
                run,
                status=EvalRunStatus.FAILED,
                completed_at=self._now(),
                failure_message="评测执行失败，请稍后重试。",
            )
            await self._repository.update_run(failed)
            await self._repository.commit()
            raise

    async def get_run(self, run_id: UUID) -> EvaluationRunDetail:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise EvalRunNotFoundError("评测运行不存在。")
        results = tuple(await self._repository.list_results(run.id))
        cases_by_id: dict[UUID, EvalCase] = {}
        for result in results:
            case = await self._repository.get_case(result.eval_case_id)
            if case is not None:
                cases_by_id[case.id] = case
        return EvaluationRunDetail(run=run, results=results, cases_by_id=cases_by_id)

    async def review_result(
        self, *, result_id: UUID, reviewer_score: float, reviewer_note: str | None
    ) -> EvalResult:
        if reviewer_score not in {0.0, 0.5, 1.0}:
            raise ValueError("人工评分只能是 0、0.5 或 1。")
        result = await self._repository.get_result(result_id)
        if result is None:
            raise EvalResultNotFoundError("评测结果不存在。")
        updated = replace(
            result,
            reviewer_score=reviewer_score,
            reviewer_note=self._normalize_optional(reviewer_note, maximum=1_000),
        )
        await self._repository.update_result(updated)
        await self._repository.commit()
        return updated

    async def _run_case(self, case: EvalCase) -> RagAnswer:
        if case.scope is EvalScope.OWNER:
            return await self._runner.answer_owner(
                space_id=case.space_id, question=case.question
            )
        return await self._runner.answer_public(
            space_id=case.space_id,
            category_ids=case.category_ids,
            question=case.question,
        )

    async def _require_active_space(self, space_id: UUID) -> None:
        if not await self._repository.has_active_space(space_id):
            raise EvalCaseNotFoundError("知识空间不存在。")

    async def _require_case(self, case_id: UUID) -> EvalCase:
        case = await self._repository.get_case(case_id)
        if case is None:
            raise EvalCaseNotFoundError("测试题不存在。")
        return case

    @staticmethod
    def _validate_scope_categories(
        scope: EvalScope, category_ids: Sequence[UUID]
    ) -> tuple[UUID, ...]:
        normalized = tuple(dict.fromkeys(category_ids))
        if scope is EvalScope.OWNER and normalized:
            raise ValueError("所有者范围测试不能指定公开分类。")
        if scope is not EvalScope.OWNER and not normalized:
            raise ValueError("公开范围测试至少需要一个分类。")
        return normalized

    @staticmethod
    def _normalize_required(value: str, *, field: str, maximum: int) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field}不能为空。")
        if len(normalized) > maximum:
            raise ValueError(f"{field}不能超过 {maximum} 个字符。")
        return normalized

    @staticmethod
    def _normalize_optional(value: str | None, *, maximum: int) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > maximum:
            raise ValueError(f"说明不能超过 {maximum} 个字符。")
        return normalized or None

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
