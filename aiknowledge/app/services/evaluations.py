from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.conversations import (
    EvalAccessDeniedError,
    EvalCase,
    EvalCaseInUseError,
    EvalCaseNotFoundError,
    EvalResult,
    EvalResultNotFoundError,
    EvalRun,
    EvalRunNotFoundError,
    EvalSetVersion,
    EvalVersionNotFoundError,
    EvalRunStatus,
    EvalScope,
    EvaluationRunComparison,
    EvaluationRunDetail,
)
from app.domain.users import SpaceRole
from app.domain.rag import AnswerStatus, RagAnswer


_UNSET = object()


class EvaluationRepository(Protocol):
    async def has_active_space(self, space_id: UUID) -> bool: ...

    async def has_space_access(self, *, space_id: UUID, user_id: UUID) -> bool: ...

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None: ...

    async def add_case(self, case: EvalCase) -> None: ...

    async def list_cases(self, space_id: UUID) -> list[EvalCase]: ...

    async def get_case(self, case_id: UUID) -> EvalCase | None: ...

    async def update_case(self, case: EvalCase) -> None: ...

    async def delete_case(self, case_id: UUID) -> None: ...

    async def has_results_for_case(self, case_id: UUID) -> bool: ...

    async def add_run(self, run: EvalRun) -> None: ...

    async def get_run(self, run_id: UUID) -> EvalRun | None: ...

    async def list_runs(self, space_id: UUID, limit: int = 20) -> list[EvalRun]: ...

    async def add_version(self, version: EvalSetVersion) -> None: ...

    async def list_versions(self, space_id: UUID, limit: int = 20) -> list[EvalSetVersion]: ...

    async def get_version(self, version_id: UUID) -> EvalSetVersion | None: ...

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
        owner_user_id: UUID | None = None,
    ) -> EvalCase:
        await self._require_owner_space(
            space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR
        )
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

    async def list_cases(self, space_id: UUID, *, owner_user_id: UUID | None = None) -> list[EvalCase]:
        await self._require_owner_space(space_id, owner_user_id=owner_user_id)
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
        owner_user_id: UUID | None = None,
    ) -> EvalCase:
        case = await self._require_case(case_id)
        await self._require_owner_space(
            case.space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR
        )
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

    async def delete_case(self, case_id: UUID, *, owner_user_id: UUID | None = None) -> None:
        case = await self._require_case(case_id)
        await self._require_owner_space(
            case.space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR
        )
        result_checker = getattr(self._repository, "has_results_for_case", None)
        if result_checker is not None and await result_checker(case.id):
            raise EvalCaseInUseError("该测试题已有历史评测结果，不能删除；可以直接编辑题目。")
        await self._repository.delete_case(case.id)
        await self._repository.commit()

    async def run(self, *, space_id: UUID, owner_user_id: UUID | None = None) -> EvaluationRunDetail:
        await self._require_owner_space(
            space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR
        )
        cases = tuple(await self._repository.list_cases(space_id))
        return await self._execute_run(space_id=space_id, cases=cases)

    async def _execute_run(
        self,
        *,
        space_id: UUID,
        cases: Sequence[EvalCase],
        snapshot: dict[str, object] | None = None,
    ) -> EvaluationRunDetail:
        started_at = self._now()
        run_snapshot = dict(snapshot or self._run_snapshot)
        # Keep the exact questions and scope used by this run alongside the
        # model/retrieval settings.  This makes historical runs reproducible
        # even after the editable live test set changes or a case is deleted.
        run_snapshot["eval_cases"] = [self._case_to_snapshot(case) for case in cases]
        run = EvalRun(
            id=self._id_factory(),
            space_id=space_id,
            status=EvalRunStatus.RUNNING,
            retrieval_config_snapshot=run_snapshot,
            created_at=started_at,
            started_at=started_at,
        )
        await self._repository.add_run(run)
        # A model timeout or process crash must never make the run invisible.
        await self._repository.commit()
        try:
            results: list[EvalResult] = []
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

    async def get_run(self, run_id: UUID, *, owner_user_id: UUID | None = None) -> EvaluationRunDetail:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise EvalRunNotFoundError("评测运行不存在。")
        await self._require_owner_space(run.space_id, owner_user_id=owner_user_id)
        results = tuple(await self._repository.list_results(run.id))
        cases_by_id = self._cases_from_run_snapshot(run)
        if not cases_by_id:
            # Compatibility for runs written before case snapshots were added.
            for result in results:
                case = await self._repository.get_case(result.eval_case_id)
                if case is not None:
                    cases_by_id[case.id] = case
        return EvaluationRunDetail(run=run, results=results, cases_by_id=cases_by_id)

    async def compare_runs(
        self,
        *,
        baseline_run_id: UUID,
        candidate_run_id: UUID,
        owner_user_id: UUID | None = None,
    ) -> EvaluationRunComparison:
        """Load two immutable run/result snapshots from the same space.

        The comparison deliberately goes through ``get_run`` for both sides,
        so the same membership checks and result snapshot semantics apply as
        when a user opens an individual run.  Cross-space comparisons are
        rejected without revealing the other run's existence.
        """

        if baseline_run_id == candidate_run_id:
            raise ValueError("基线和候选评测运行必须不同。")
        baseline = await self.get_run(baseline_run_id, owner_user_id=owner_user_id)
        candidate = await self.get_run(candidate_run_id, owner_user_id=owner_user_id)
        if baseline.run.space_id != candidate.run.space_id:
            raise EvalRunNotFoundError("只能比较同一知识空间内的评测运行。")
        return EvaluationRunComparison(baseline=baseline, candidate=candidate)

    async def list_runs(
        self, space_id: UUID, *, owner_user_id: UUID | None = None, limit: int = 20
    ) -> list[EvalRun]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        await self._require_owner_space(space_id, owner_user_id=owner_user_id)
        return await self._repository.list_runs(space_id, limit=limit)

    async def create_version(
        self,
        *,
        space_id: UUID,
        label: str,
        owner_user_id: UUID | None = None,
    ) -> EvalSetVersion:
        """Freeze the current test set so future edits cannot change a run."""

        await self._require_owner_space(
            space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR
        )
        normalized_label = self._normalize_required(label, field="版本名称", maximum=120)
        cases = tuple(await self._repository.list_cases(space_id))
        if not cases:
            raise ValueError("至少需要一条测试题才能创建版本。")
        versions_reader = getattr(self._repository, "list_versions", None)
        versions = (
            await versions_reader(space_id, limit=50)
            if versions_reader is not None
            else []
        )
        version_number = max((item.version_number for item in versions), default=0) + 1
        version = EvalSetVersion(
            id=self._id_factory(),
            space_id=space_id,
            version_number=version_number,
            label=normalized_label,
            cases=cases,
            created_at=self._now(),
        )
        add_version = getattr(self._repository, "add_version", None)
        if add_version is None:
            raise RuntimeError("当前评测存储不支持版本快照。")
        await add_version(version)
        await self._repository.commit()
        return version

    async def list_versions(
        self, space_id: UUID, *, owner_user_id: UUID | None = None, limit: int = 20
    ) -> list[EvalSetVersion]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        await self._require_owner_space(space_id, owner_user_id=owner_user_id)
        reader = getattr(self._repository, "list_versions", None)
        if reader is None:
            return []
        return await reader(space_id, limit=limit)

    async def get_version(
        self, version_id: UUID, *, owner_user_id: UUID | None = None
    ) -> EvalSetVersion:
        reader = getattr(self._repository, "get_version", None)
        version = await reader(version_id) if reader is not None else None
        if version is None:
            raise EvalVersionNotFoundError("评测集版本不存在。")
        await self._require_owner_space(version.space_id, owner_user_id=owner_user_id)
        return version

    async def run_version(
        self, version_id: UUID, *, owner_user_id: UUID | None = None
    ) -> EvaluationRunDetail:
        version = await self.get_version(version_id, owner_user_id=owner_user_id)
        await self._require_owner_space(
            version.space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR
        )
        snapshot = dict(self._run_snapshot)
        snapshot.update(
            {
                "eval_set_version_id": str(version.id),
                "eval_set_version_number": version.version_number,
            }
        )
        return await self._execute_run(
            space_id=version.space_id, cases=version.cases, snapshot=snapshot
        )

    async def review_result(
        self, *, result_id: UUID, reviewer_score: float, reviewer_note: str | None, owner_user_id: UUID | None = None
    ) -> EvalResult:
        if reviewer_score not in {0.0, 0.5, 1.0}:
            raise ValueError("人工评分只能是 0、0.5 或 1。")
        result = await self._repository.get_result(result_id)
        if result is None:
            raise EvalResultNotFoundError("评测结果不存在。")
        case = await self._repository.get_case(result.eval_case_id)
        if case is None:
            raise EvalResultNotFoundError("评测结果不存在。")
        await self._require_owner_space(
            case.space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR
        )
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

    async def _require_owner_space(
        self,
        space_id: UUID,
        *,
        owner_user_id: UUID | None,
        minimum_role: SpaceRole = SpaceRole.MEMBER,
    ) -> None:
        if owner_user_id is None:
            await self._require_active_space(space_id)
            return
        role_reader = getattr(self._repository, "get_space_role", None)
        if role_reader is not None:
            role = await role_reader(space_id=space_id, user_id=owner_user_id)
            if role is None:
                raise EvalCaseNotFoundError("知识空间不存在。")
            order = {SpaceRole.MEMBER: 0, SpaceRole.EDITOR: 1, SpaceRole.OWNER: 2}
            if order[role] < order[minimum_role]:
                raise EvalAccessDeniedError("你没有执行评测操作的权限。")
            return
        checker = getattr(self._repository, "has_space_access", None)
        if checker is None or not await checker(space_id=space_id, user_id=owner_user_id):
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

    @staticmethod
    def _case_to_snapshot(case: EvalCase) -> dict[str, object]:
        return {
            "id": str(case.id),
            "space_id": str(case.space_id),
            "question": case.question,
            "expected_answer": case.expected_answer,
            "expected_document_ids": [str(value) for value in case.expected_document_ids],
            "scope": case.scope.value,
            "category_ids": [str(value) for value in case.category_ids],
            "created_at": case.created_at.isoformat(),
        }

    @classmethod
    def _cases_from_run_snapshot(cls, run: EvalRun) -> dict[UUID, EvalCase]:
        raw_cases = run.retrieval_config_snapshot.get("eval_cases")
        if not isinstance(raw_cases, list):
            return {}
        cases: dict[UUID, EvalCase] = {}
        for raw in raw_cases:
            if not isinstance(raw, dict):
                continue
            try:
                case = cls._case_from_snapshot(raw)
            except (KeyError, TypeError, ValueError):
                continue
            cases[case.id] = case
        return cases

    @staticmethod
    def _case_from_snapshot(raw: dict[str, object]) -> EvalCase:
        return EvalCase(
            id=UUID(str(raw["id"])),
            space_id=UUID(str(raw["space_id"])),
            question=str(raw["question"]),
            expected_answer=(
                str(raw["expected_answer"])
                if raw.get("expected_answer") is not None
                else None
            ),
            expected_document_ids=tuple(
                UUID(str(value)) for value in raw.get("expected_document_ids", [])  # type: ignore[union-attr]
            ),
            scope=EvalScope(str(raw["scope"])),
            category_ids=tuple(
                UUID(str(value)) for value in raw.get("category_ids", [])  # type: ignore[union-attr]
            ),
            created_at=datetime.fromisoformat(str(raw["created_at"])),
        )
