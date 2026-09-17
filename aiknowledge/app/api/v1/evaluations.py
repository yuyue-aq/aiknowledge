from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session, get_optional_current_user
from app.core.errors import AppError
from app.domain.conversations import (
    EvalCase,
    EvalAccessDeniedError,
    EvalCaseNotFoundError,
    EvalResult,
    EvalResultNotFoundError,
    EvalRun,
    EvalRunNotFoundError,
    EvalSetVersion,
    EvalVersionNotFoundError,
    EvalScope,
    EvaluationRunComparison,
    EvaluationRunDetail,
)
from app.domain.users import User


router = APIRouter(tags=["evaluations"])


class EvaluationServicePort(Protocol):
    async def create_case(self, **kwargs: object) -> EvalCase: ...

    async def list_cases(self, space_id: UUID, **kwargs: object) -> list[EvalCase]: ...

    async def update_case(self, case_id: UUID, **kwargs: object) -> EvalCase: ...

    async def delete_case(self, case_id: UUID, **kwargs: object) -> None: ...

    async def run(self, *, space_id: UUID, **kwargs: object) -> EvaluationRunDetail: ...

    async def get_run(self, run_id: UUID, **kwargs: object) -> EvaluationRunDetail: ...

    async def compare_runs(self, **kwargs: object) -> EvaluationRunComparison: ...

    async def list_runs(self, space_id: UUID, **kwargs: object) -> list[EvalRun]: ...

    async def create_version(self, **kwargs: object) -> EvalSetVersion: ...

    async def list_versions(self, space_id: UUID, **kwargs: object) -> list[EvalSetVersion]: ...

    async def get_version(self, version_id: UUID, **kwargs: object) -> EvalSetVersion: ...

    async def run_version(self, version_id: UUID, **kwargs: object) -> EvaluationRunDetail: ...

    async def review_result(self, **kwargs: object) -> EvalResult: ...


def get_evaluation_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> EvaluationServicePort:
    return request.app.state.evaluation_service_factory(session)


class EvalCaseCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=2_000)
    expected_answer: str | None = Field(default=None, max_length=5_000)
    expected_document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    scope: EvalScope = EvalScope.OWNER
    category_ids: list[UUID] = Field(default_factory=list, max_length=100)


class EvalCaseUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str | None = Field(default=None, min_length=1, max_length=2_000)
    expected_answer: str | None = Field(default=None, max_length=5_000)
    expected_document_ids: list[UUID] | None = Field(default=None, max_length=100)
    scope: EvalScope | None = None
    category_ids: list[UUID] | None = Field(default=None, max_length=100)


class EvalCaseResponse(BaseModel):
    id: UUID
    space_id: UUID
    question: str
    expected_answer: str | None
    expected_document_ids: list[UUID]
    scope: EvalScope
    category_ids: list[UUID]
    created_at: datetime

    @classmethod
    def from_domain(cls, case: EvalCase) -> "EvalCaseResponse":
        return cls(
            id=case.id,
            space_id=case.space_id,
            question=case.question,
            expected_answer=case.expected_answer,
            expected_document_ids=list(case.expected_document_ids),
            scope=case.scope,
            category_ids=list(case.category_ids),
            created_at=case.created_at,
        )


class EvalCaseListResponse(BaseModel):
    items: list[EvalCaseResponse]


class EvalSetVersionCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=120)


class EvalSetVersionResponse(BaseModel):
    id: UUID
    space_id: UUID
    version_number: int
    label: str
    cases: list[EvalCaseResponse]
    created_at: datetime

    @classmethod
    def from_domain(cls, version: EvalSetVersion) -> "EvalSetVersionResponse":
        return cls(
            id=version.id,
            space_id=version.space_id,
            version_number=version.version_number,
            label=version.label,
            cases=[EvalCaseResponse.from_domain(case) for case in version.cases],
            created_at=version.created_at,
        )


class EvalSetVersionListResponse(BaseModel):
    items: list[EvalSetVersionResponse]


class EvalResultResponse(BaseModel):
    id: UUID
    eval_case_id: UUID
    answer_status: str
    answer: str
    citation_count: int
    reviewer_score: float | None
    reviewer_note: str | None

    @classmethod
    def from_domain(cls, result: EvalResult) -> "EvalResultResponse":
        return cls(
            id=result.id,
            eval_case_id=result.eval_case_id,
            answer_status=result.answer_status.value,
            answer=result.answer,
            citation_count=result.citation_count,
            reviewer_score=result.reviewer_score,
            reviewer_note=result.reviewer_note,
        )


class EvalRunResponse(BaseModel):
    id: UUID
    space_id: UUID
    status: str
    retrieval_config_snapshot: dict[str, object]
    started_at: datetime | None
    completed_at: datetime | None
    failure_message: str | None
    created_at: datetime

    @classmethod
    def from_domain(cls, run: EvalRun) -> "EvalRunResponse":
        return cls(
            id=run.id,
            space_id=run.space_id,
            status=run.status.value,
            retrieval_config_snapshot=run.retrieval_config_snapshot,
            started_at=run.started_at,
            completed_at=run.completed_at,
            failure_message=run.failure_message,
            created_at=run.created_at,
        )


class EvalRunListResponse(BaseModel):
    items: list[EvalRunResponse]


class EvalSummaryResponse(BaseModel):
    total: int
    answered: int
    insufficient_evidence: int
    out_of_scope: int
    failed: int
    citation_count: int
    out_of_scope_violations: int
    reviewed_correct: int
    reviewed_partial: int
    reviewed_incorrect: int
    answered_rate: float = 0.0
    citation_rate: float = 0.0
    reviewed_accuracy: float | None = None


class EvalRunDetailResponse(BaseModel):
    run: EvalRunResponse
    results: list[EvalResultResponse]
    summary: EvalSummaryResponse

    @classmethod
    def from_domain(cls, detail: EvaluationRunDetail) -> "EvalRunDetailResponse":
        return cls(
            run=EvalRunResponse.from_domain(detail.run),
            results=[EvalResultResponse.from_domain(result) for result in detail.results],
            summary=_summary(detail),
        )


class EvalRunComparisonResponse(BaseModel):
    baseline: EvalRunResponse
    candidate: EvalRunResponse
    baseline_summary: EvalSummaryResponse
    candidate_summary: EvalSummaryResponse
    delta: dict[str, float | None]

    @classmethod
    def from_domain(cls, comparison: EvaluationRunComparison) -> "EvalRunComparisonResponse":
        baseline_summary = _summary(comparison.baseline)
        candidate_summary = _summary(comparison.candidate)
        metric_names = (
            "total",
            "answered",
            "insufficient_evidence",
            "out_of_scope",
            "failed",
            "citation_count",
            "out_of_scope_violations",
            "reviewed_correct",
            "reviewed_partial",
            "reviewed_incorrect",
            "answered_rate",
            "citation_rate",
            "reviewed_accuracy",
        )
        delta: dict[str, float | None] = {}
        for name in metric_names:
            baseline_value = getattr(baseline_summary, name)
            candidate_value = getattr(candidate_summary, name)
            if baseline_value is None or candidate_value is None:
                delta[name] = None
            else:
                delta[name] = float(candidate_value - baseline_value)
        return cls(
            baseline=EvalRunResponse.from_domain(comparison.baseline.run),
            candidate=EvalRunResponse.from_domain(comparison.candidate.run),
            baseline_summary=baseline_summary,
            candidate_summary=candidate_summary,
            delta=delta,
        )


class EvalResultReviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reviewer_score: float
    reviewer_note: str | None = Field(default=None, max_length=1_000)


def _summary(detail: EvaluationRunDetail) -> EvalSummaryResponse:
    results = detail.results
    return EvalSummaryResponse(
        total=len(results),
        answered=sum(result.answer_status.value == "ANSWERED" for result in results),
        insufficient_evidence=sum(
            result.answer_status.value == "INSUFFICIENT_EVIDENCE" for result in results
        ),
        out_of_scope=sum(result.answer_status.value == "OUT_OF_SCOPE" for result in results),
        failed=sum(result.answer_status.value == "FAILED" for result in results),
        citation_count=sum(result.citation_count for result in results),
        out_of_scope_violations=sum(
            detail.cases_by_id.get(result.eval_case_id) is not None
            and detail.cases_by_id[result.eval_case_id].scope is EvalScope.OUT_OF_SCOPE
            and result.answer_status.value == "ANSWERED"
            for result in results
        ),
        reviewed_correct=sum(result.reviewer_score == 1.0 for result in results),
        reviewed_partial=sum(result.reviewer_score == 0.5 for result in results),
        reviewed_incorrect=sum(result.reviewer_score == 0.0 for result in results),
        answered_rate=(
            sum(result.answer_status.value == "ANSWERED" for result in results) / len(results)
            if results
            else 0.0
        ),
        citation_rate=(
            sum(result.citation_count > 0 for result in results) / len(results)
            if results
            else 0.0
        ),
        reviewed_accuracy=(
            (
                sum(
                    (result.reviewer_score or 0.0)
                    for result in results
                    if result.reviewer_score is not None
                )
                / sum(result.reviewer_score is not None for result in results)
            )
            if any(result.reviewer_score is not None for result in results)
            else None
        ),
    )


def _translate_evaluation_error(error: Exception) -> None:
    if isinstance(error, EvalAccessDeniedError):
        raise AppError(code="EVAL_ACCESS_DENIED", message=str(error), status_code=403) from error
    if isinstance(error, EvalCaseNotFoundError):
        raise AppError(code="EVAL_CASE_NOT_FOUND", message=str(error), status_code=404) from error
    if isinstance(error, EvalRunNotFoundError):
        raise AppError(code="EVAL_RUN_NOT_FOUND", message=str(error), status_code=404) from error
    if isinstance(error, EvalResultNotFoundError):
        raise AppError(code="EVAL_RESULT_NOT_FOUND", message=str(error), status_code=404) from error
    if isinstance(error, EvalVersionNotFoundError):
        raise AppError(code="EVAL_VERSION_NOT_FOUND", message=str(error), status_code=404) from error
    if isinstance(error, ValueError):
        raise AppError(code="EVAL_INVALID", message=str(error), status_code=422) from error
    raise error


@router.get("/spaces/{space_id}/eval-cases", response_model=EvalCaseListResponse)
async def list_eval_cases(
    space_id: UUID,
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalCaseListResponse:
    try:
        if _current_user is None:
            cases = await service.list_cases(space_id)
        else:
            cases = await service.list_cases(space_id, owner_user_id=_current_user.id)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalCaseListResponse(items=[EvalCaseResponse.from_domain(case) for case in cases])


@router.post(
    "/spaces/{space_id}/eval-cases",
    status_code=status.HTTP_201_CREATED,
    response_model=EvalCaseResponse,
)
async def create_eval_case(
    space_id: UUID,
    payload: EvalCaseCreateRequest,
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalCaseResponse:
    try:
        kwargs = {"space_id": space_id, **payload.model_dump()}
        if _current_user is not None:
            kwargs["owner_user_id"] = _current_user.id
        case = await service.create_case(**kwargs)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalCaseResponse.from_domain(case)


@router.patch("/eval-cases/{case_id}", response_model=EvalCaseResponse)
async def update_eval_case(
    case_id: UUID,
    payload: EvalCaseUpdateRequest,
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalCaseResponse:
    changes = {
        field: getattr(payload, field)
        for field in (
            "question",
            "expected_answer",
            "expected_document_ids",
            "scope",
            "category_ids",
        )
        if field in payload.model_fields_set
    }
    try:
        if _current_user is None:
            case = await service.update_case(case_id, **changes)
        else:
            case = await service.update_case(
                case_id, owner_user_id=_current_user.id, **changes
            )
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalCaseResponse.from_domain(case)


@router.delete("/eval-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_eval_case(
    case_id: UUID,
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> Response:
    try:
        if _current_user is None:
            await service.delete_case(case_id)
        else:
            await service.delete_case(case_id, owner_user_id=_current_user.id)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/spaces/{space_id}/eval-runs",
    status_code=status.HTTP_201_CREATED,
    response_model=EvalRunDetailResponse,
)
async def run_evaluation(
    space_id: UUID,
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalRunDetailResponse:
    try:
        if _current_user is None:
            detail = await service.run(space_id=space_id)
        else:
            detail = await service.run(space_id=space_id, owner_user_id=_current_user.id)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalRunDetailResponse.from_domain(detail)


@router.get("/spaces/{space_id}/eval-runs", response_model=EvalRunListResponse)
async def list_evaluation_runs(
    space_id: UUID,
    limit: int = Query(default=20, ge=1, le=50),
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalRunListResponse:
    try:
        kwargs: dict[str, object] = {"limit": limit}
        if _current_user is not None:
            kwargs["owner_user_id"] = _current_user.id
        runs = await service.list_runs(space_id, **kwargs)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalRunListResponse(items=[EvalRunResponse.from_domain(run) for run in runs])


@router.get(
    "/spaces/{space_id}/eval-runs/compare",
    response_model=EvalRunComparisonResponse,
)
async def compare_evaluation_runs(
    space_id: UUID,
    baseline_run_id: UUID = Query(...),
    candidate_run_id: UUID = Query(...),
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalRunComparisonResponse:
    try:
        kwargs: dict[str, object] = {
            "baseline_run_id": baseline_run_id,
            "candidate_run_id": candidate_run_id,
        }
        if _current_user is not None:
            kwargs["owner_user_id"] = _current_user.id
        comparison = await service.compare_runs(**kwargs)
        if (
            comparison.baseline.run.space_id != space_id
            or comparison.candidate.run.space_id != space_id
        ):
            raise EvalRunNotFoundError("评测运行不存在。")
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalRunComparisonResponse.from_domain(comparison)


@router.get("/spaces/{space_id}/eval-versions", response_model=EvalSetVersionListResponse)
async def list_evaluation_versions(
    space_id: UUID,
    limit: int = Query(default=20, ge=1, le=50),
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalSetVersionListResponse:
    try:
        kwargs: dict[str, object] = {"limit": limit}
        if _current_user is not None:
            kwargs["owner_user_id"] = _current_user.id
        versions = await service.list_versions(space_id, **kwargs)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalSetVersionListResponse(
        items=[EvalSetVersionResponse.from_domain(version) for version in versions]
    )


@router.post(
    "/spaces/{space_id}/eval-versions",
    status_code=status.HTTP_201_CREATED,
    response_model=EvalSetVersionResponse,
)
async def create_evaluation_version(
    space_id: UUID,
    payload: EvalSetVersionCreateRequest,
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalSetVersionResponse:
    kwargs: dict[str, object] = {"space_id": space_id, **payload.model_dump()}
    if _current_user is not None:
        kwargs["owner_user_id"] = _current_user.id
    try:
        version = await service.create_version(**kwargs)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalSetVersionResponse.from_domain(version)


@router.get("/eval-versions/{version_id}", response_model=EvalSetVersionResponse)
async def get_evaluation_version(
    version_id: UUID,
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalSetVersionResponse:
    try:
        kwargs = {"owner_user_id": _current_user.id} if _current_user is not None else {}
        version = await service.get_version(version_id, **kwargs)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalSetVersionResponse.from_domain(version)


@router.post(
    "/eval-versions/{version_id}/runs",
    status_code=status.HTTP_201_CREATED,
    response_model=EvalRunDetailResponse,
)
async def run_evaluation_version(
    version_id: UUID,
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalRunDetailResponse:
    try:
        kwargs = {"owner_user_id": _current_user.id} if _current_user is not None else {}
        detail = await service.run_version(version_id, **kwargs)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalRunDetailResponse.from_domain(detail)


@router.get("/eval-runs/{run_id}", response_model=EvalRunDetailResponse)
async def get_evaluation_run(
    run_id: UUID,
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalRunDetailResponse:
    try:
        if _current_user is None:
            detail = await service.get_run(run_id)
        else:
            detail = await service.get_run(run_id, owner_user_id=_current_user.id)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalRunDetailResponse.from_domain(detail)


@router.patch("/eval-results/{result_id}", response_model=EvalResultResponse)
async def review_evaluation_result(
    result_id: UUID,
    payload: EvalResultReviewRequest,
    service: EvaluationServicePort = Depends(get_evaluation_service),
    _current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
) -> EvalResultResponse:
    try:
        result = await service.review_result(
            result_id=result_id,
            **payload.model_dump(),
            **({"owner_user_id": _current_user.id} if _current_user is not None else {}),
        )
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalResultResponse.from_domain(result)
