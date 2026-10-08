from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4
import asyncio

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
from app.domain.evaluation import EvidenceRef
from app.services.evaluation_metrics import retrieval_metrics, refusal_correct


_UNSET = object()


class EvaluationSnapshotError(ValueError):
    pass


class EvaluationConfigurationError(ValueError):
    pass


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
        dispatcher=None,
    ) -> None:
        self._repository = repository
        self._runner = runner
        self._run_snapshot = dict(run_snapshot)
        self._id_factory = id_factory
        self._clock = clock
        self._dispatcher = dispatcher

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
        answerable: bool | None = None,
        expected_behavior: str | None = None,
        evidence_refs: Sequence[EvidenceRef] = (),
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
            answerable=answerable,
            expected_behavior=expected_behavior,
            evidence_refs=tuple(evidence_refs),
        )
        await self._validate_labels(case)
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
        answerable: bool | None | object = _UNSET,
        expected_behavior: str | None | object = _UNSET,
        evidence_refs: Sequence[EvidenceRef] | None = None,
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
            answerable=case.answerable if answerable is _UNSET else answerable,
            expected_behavior=case.expected_behavior if expected_behavior is _UNSET else expected_behavior,
            evidence_refs=case.evidence_refs if evidence_refs is None else tuple(evidence_refs),
        )
        await self._validate_labels(updated)
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
        run = await self._prepare_run(space_id=space_id, cases=cases, snapshot=snapshot)
        detail = await self.execute_pending(run.id)
        if detail is None:
            raise RuntimeError('评测任务已由其他 Worker 接管。')
        return detail

    async def _prepare_run(self, *, space_id: UUID, cases: Sequence[EvalCase], snapshot=None, owner_user_id=None) -> EvalRun:
        if not cases:
            raise ValueError('至少需要一条测试题才能运行评测。')
        started_at = self._now()
        run_snapshot = dict(snapshot or self._run_snapshot)
        # Keep the exact questions and scope used by this run alongside the
        # model/retrieval settings.  This makes historical runs reproducible
        # even after the editable live test set changes or a case is deleted.
        run_snapshot["eval_cases"] = [self._case_to_snapshot(case) for case in cases]
        manifest_reader = getattr(self._repository, 'capture_knowledge_manifest', None)
        if manifest_reader is not None:
            run_snapshot['knowledge_manifest'] = await manifest_reader(space_id)
        if owner_user_id is not None:
            run_snapshot['owner_user_id'] = str(owner_user_id)
        run_id = self._id_factory()
        run = EvalRun(
            id=run_id,
            space_id=space_id,
            status=EvalRunStatus.PENDING,
            retrieval_config_snapshot=run_snapshot,
            created_at=started_at,
            progress_total=len(cases),
            task_id=str(run_id),
        )
        await self._repository.add_run(run)
        # A model timeout or process crash must never make the run invisible.
        await self._repository.commit()
        return run

    async def enqueue_run(self, *, space_id: UUID | None = None, version_id: UUID | None = None, owner_user_id: UUID | None = None, strategy: str | None = None) -> EvalRun:
        snapshot = dict(self._run_snapshot)
        if strategy is not None:
            if strategy not in ('dense','hybrid'):raise ValueError('不支持的检索方式。')
            snapshot['retrieval_strategy']=strategy
        if version_id is not None:
            version = await self.get_version(version_id, owner_user_id=owner_user_id)
            space_id, cases = version.space_id, version.cases
            snapshot.update({'eval_set_version_id': str(version.id), 'eval_set_version_number': version.version_number})
        else:
            if space_id is None:
                raise ValueError('请选择知识空间。')
            await self._require_owner_space(space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR)
            cases = tuple(await self._repository.list_cases(space_id))
        await self._require_owner_space(space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR)
        run = await self._prepare_run(space_id=space_id, cases=cases, snapshot=snapshot, owner_user_id=owner_user_id)
        return await self._dispatch(run)

    async def _dispatch(self, run: EvalRun) -> EvalRun:
        try:
            if self._dispatcher is None:
                raise RuntimeError('queue unavailable')
            await self._dispatcher.enqueue_evaluation(run.id)
        except Exception:
            marker = getattr(self._repository, 'mark_dispatch_failure', None)
            if marker is not None:
                run = await marker(run.id)
            else:
                current = await self._repository.get_run(run.id)
                run = current or run
                if run.status is EvalRunStatus.PENDING:
                    run = replace(run, failure_code='QUEUE_UNAVAILABLE', failure_message='评测队列暂不可用，可稍后补投此任务。')
                    await self._repository.update_run(run)
            await self._repository.commit()
        return run

    async def execute_pending(self, run_id: UUID) -> EvaluationRunDetail | None:
        lease_token = str(uuid4())
        claimer = getattr(self._repository, 'claim_run', None)
        if claimer is not None:
            run = await claimer(run_id, lease_token=lease_token, lease_seconds=1200)
            await self._repository.commit()
        else:
            run = await self._repository.get_run(run_id)
            if run is not None and run.status is not EvalRunStatus.COMPLETED:
                run = replace(run, status=EvalRunStatus.RUNNING, started_at=run.started_at or self._now(), lease_owner=lease_token)
                await self._repository.update_run(run)
                await self._repository.commit()
            else:
                run = None
        if run is None:
            return None
        cases_by_id = self._cases_from_run_snapshot(run)
        cases = tuple(cases_by_id.values())
        results = list(await self._repository.list_results(run.id))
        completed_ids = {result.eval_case_id for result in results}
        run_snapshot = run.retrieval_config_snapshot
        manifest_reader = getattr(self._repository, 'capture_knowledge_manifest', None)

        async def verify_manifest():
            owner_id = run_snapshot.get('owner_user_id')
            if owner_id is not None:
                await self._require_owner_space(run.space_id, owner_user_id=UUID(owner_id), minimum_role=SpaceRole.EDITOR)
            if manifest_reader is not None:
                current = await manifest_reader(run.space_id)
                saved = run_snapshot.get('knowledge_manifest')
                if not saved or current.get('manifest_digest') != saved.get('manifest_digest'):
                    raise EvaluationSnapshotError('知识集合已变化，请创建新运行。')
                # Do not retain a DB transaction while waiting for embeddings/LLM.
                await self._repository.commit()

        try:
            if any(run_snapshot.get(key) != value for key, value in self._run_snapshot.items() if key!='retrieval_strategy') or run_snapshot.get('retrieval_strategy','dense') not in ('dense','hybrid'):
                raise EvaluationConfigurationError('评测配置已变化，请恢复原配置或创建新运行。')
            if len(cases) != run.progress_total:
                raise EvaluationSnapshotError('题集快照无效，请创建新运行。')
            for case in cases:
                if case.id in completed_ids:
                    continue
                await verify_manifest()
                answer = await asyncio.wait_for(self._run_case(case, strategy=run_snapshot.get('retrieval_strategy')), timeout=900)
                await verify_manifest()
                manifest = run_snapshot.get('knowledge_manifest') or {}
                versions = {UUID(value) for value in manifest.get('document_versions', [])} if manifest else None
                metrics = retrieval_metrics(case, list(answer.retrieval_chunks), k=int(run_snapshot.get('candidate_limit', 12)),
                    available_versions=versions) if answer.execution_snapshot is not None else None
                if metrics is not None:
                    metrics['refusal_correct'] = refusal_correct(case, answer.status)
                result = EvalResult(
                    id=self._id_factory(),
                    eval_run_id=run.id,
                    eval_case_id=case.id,
                    answer_status=answer.status,
                    answer=answer.answer,
                    citation_count=len(answer.citations),
                    execution_snapshot=answer.execution_snapshot,
                    retrieval_metrics=metrics,
                    failure_code=(answer.execution_snapshot or {}).get('failure_code') or ('MODEL_FAILED' if answer.status is AnswerStatus.FAILED else None),
                )
                checkpoint = getattr(self._repository, 'checkpoint_result', None)
                if checkpoint is not None:
                    if not await checkpoint(result, lease_token=lease_token, lease_seconds=1200):
                        return None
                else:
                    await self._repository.add_result(result)
                    await self._repository.update_run(replace(run, progress_completed=len(results)+1, heartbeat_at=self._now()))
                await self._repository.commit()
                results.append(result)
                run = replace(run, progress_completed=len(results), heartbeat_at=self._now())
            completed = replace(
                run,
                status=EvalRunStatus.COMPLETED,
                completed_at=self._now(),
                failure_code=None,
                failure_message=None,
                lease_owner=None,
                lease_expires_at=None,
            )
            finisher = getattr(self._repository, 'finish_run', None)
            if finisher is not None:
                if not await finisher(completed, lease_token=lease_token):
                    return None
            else:
                await self._repository.update_run(completed)
            await self._repository.commit()
            return EvaluationRunDetail(
                run=completed,
                results=tuple(results),
                cases_by_id={case.id: case for case in cases},
            )
        except Exception as exc:
            rollback = getattr(self._repository, 'rollback', None)
            if rollback is not None:
                await rollback()
            failed = replace(
                run,
                status=EvalRunStatus.FAILED,
                completed_at=self._now(),
                failure_message=('评测配置已变化，请恢复原配置或创建新运行。' if isinstance(exc, EvaluationConfigurationError)
                    else '知识集合或题集快照已变化，请创建新运行。' if isinstance(exc, EvaluationSnapshotError)
                    else '评测执行失败，可恢复未完成的题目。'),
                failure_code=('EVAL_CONFIG_MISMATCH' if isinstance(exc, EvaluationConfigurationError)
                    else 'EVAL_SNAPSHOT_INVALID' if isinstance(exc, EvaluationSnapshotError) else 'EVAL_EXECUTION_FAILED'),
                lease_owner=None,
                lease_expires_at=None,
            )
            finisher = getattr(self._repository, 'finish_run', None)
            if finisher is not None:
                if not await finisher(failed, lease_token=lease_token):
                    return None
            else:
                await self._repository.update_run(failed)
            await self._repository.commit()
            return EvaluationRunDetail(run=failed, results=tuple(results), cases_by_id=cases_by_id)

    async def redispatch_run(self, run_id: UUID, *, owner_user_id: UUID | None = None) -> EvalRun:
        detail = await self.get_run(run_id, owner_user_id=owner_user_id)
        await self._require_owner_space(detail.run.space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR)
        if detail.run.status is EvalRunStatus.COMPLETED:
            raise ValueError('已完成的运行请通过新运行进行复测。')
        preparer = getattr(self._repository, 'prepare_redispatch', None)
        if preparer is not None:
            run = await preparer(run_id)
            if run is None:
                raise ValueError('任务仍在执行中，请稍后检查进度。')
        else:
            if detail.run.status is EvalRunStatus.RUNNING:
                raise ValueError('任务仍在执行中，请稍后检查进度。')
            run = replace(detail.run, status=EvalRunStatus.PENDING, failure_code=None, failure_message=None)
            await self._repository.update_run(run)
        await self._repository.commit()
        return await self._dispatch(run)

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
        case_ids: Sequence[UUID] | None = None,
        owner_user_id: UUID | None = None,
    ) -> EvalSetVersion:
        """Freeze the current test set so future edits cannot change a run."""

        await self._require_owner_space(
            space_id, owner_user_id=owner_user_id, minimum_role=SpaceRole.EDITOR
        )
        normalized_label = self._normalize_required(label, field="版本名称", maximum=120)
        cases = tuple(await self._repository.list_cases(space_id))
        if case_ids is not None:
            if not case_ids or len(case_ids) > 50 or len(set(case_ids)) != len(case_ids):
                raise ValueError("选择 1—50 条不重复的测试题。")
            available = {case.id: case for case in cases}
            if any(case_id not in available for case_id in case_ids):
                raise ValueError("只能选择当前空间的测试题。")
            cases = tuple(available[case_id] for case_id in case_ids)
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

    async def _run_case(self, case: EvalCase, *, strategy: str | None = None) -> RagAnswer:
        extra={'strategy':strategy} if strategy is not None else {}
        if case.scope is EvalScope.OWNER:
            return await self._runner.answer_owner(
                space_id=case.space_id, question=case.question, **extra
            )
        return await self._runner.answer_public(
            space_id=case.space_id,
            category_ids=case.category_ids,
            question=case.question,
            **extra,
        )

    async def _validate_labels(self, case: EvalCase):
        if case.answerable is not None and not isinstance(case.answerable, bool):
            raise ValueError('可回答性必须为布尔值。')
        if case.expected_behavior is not None and case.expected_behavior not in {'ANSWERED', 'INSUFFICIENT_EVIDENCE', 'OUT_OF_SCOPE', 'CONFLICT'}:
            raise ValueError('预期行为无效。')
        if case.answerable is False and case.expected_behavior == 'ANSWERED':
            raise ValueError('不可回答的题目不能标为应回答。')
        if len(case.evidence_refs) > 100 or any(not isinstance(ref, EvidenceRef) for ref in case.evidence_refs):
            raise ValueError('证据标注无效。')
        validator = getattr(self._repository, 'validate_case_evidence', None)
        if validator is not None and not await validator(space_id=case.space_id,
            expected_document_ids=case.expected_document_ids, evidence_refs=case.evidence_refs):
            raise ValueError('证据不属于当前空间、已失效或原文区间不匹配。')

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
            order = {SpaceRole.MEMBER: 0, SpaceRole.EDITOR: 1, SpaceRole.ADMIN: 2, SpaceRole.OWNER: 3}
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
            'answerable': case.answerable,
            'expected_behavior': case.expected_behavior,
            'evidence_refs': [ref.to_dict() for ref in case.evidence_refs],
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
            answerable=raw.get('answerable'),
            expected_behavior=raw.get('expected_behavior'),
            evidence_refs=tuple(EvidenceRef.from_dict(ref) for ref in raw.get('evidence_refs', [])),
        )
