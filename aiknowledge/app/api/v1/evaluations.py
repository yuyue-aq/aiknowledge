from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database_session
from app.core.errors import AppError
from app.domain.conversations import (
    EvalCase,
    EvalCaseNotFoundError,
    EvalResult,
    EvalResultNotFoundError,
    EvalRun,
    EvalRunNotFoundError,
    EvalScope,
    EvaluationRunDetail,
)


router = APIRouter(tags=["evaluations"])


class EvaluationServicePort(Protocol):
    async def create_case(self, **kwargs: object) -> EvalCase: ...

    async def list_cases(self, space_id: UUID) -> list[EvalCase]: ...

    async def update_case(self, case_id: UUID, **kwargs: object) -> EvalCase: ...

    async def delete_case(self, case_id: UUID) -> None: ...

    async def run(self, *, space_id: UUID) -> EvaluationRunDetail: ...

    async def get_run(self, run_id: UUID) -> EvaluationRunDetail: ...

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
    )


def _translate_evaluation_error(error: Exception) -> None:
    if isinstance(error, EvalCaseNotFoundError):
        raise AppError(code="EVAL_CASE_NOT_FOUND", message=str(error), status_code=404) from error
    if isinstance(error, EvalRunNotFoundError):
        raise AppError(code="EVAL_RUN_NOT_FOUND", message=str(error), status_code=404) from error
    if isinstance(error, EvalResultNotFoundError):
        raise AppError(code="EVAL_RESULT_NOT_FOUND", message=str(error), status_code=404) from error
    if isinstance(error, ValueError):
        raise AppError(code="EVAL_INVALID", message=str(error), status_code=422) from error
    raise error


@router.get("/spaces/{space_id}/eval-cases", response_model=EvalCaseListResponse)
async def list_eval_cases(
    space_id: UUID,
    service: EvaluationServicePort = Depends(get_evaluation_service),
) -> EvalCaseListResponse:
    try:
        cases = await service.list_cases(space_id)
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
) -> EvalCaseResponse:
    try:
        case = await service.create_case(space_id=space_id, **payload.model_dump())
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalCaseResponse.from_domain(case)


@router.patch("/eval-cases/{case_id}", response_model=EvalCaseResponse)
async def update_eval_case(
    case_id: UUID,
    payload: EvalCaseUpdateRequest,
    service: EvaluationServicePort = Depends(get_evaluation_service),
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
        case = await service.update_case(case_id, **changes)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalCaseResponse.from_domain(case)


@router.delete("/eval-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_eval_case(
    case_id: UUID,
    service: EvaluationServicePort = Depends(get_evaluation_service),
) -> Response:
    try:
        await service.delete_case(case_id)
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
) -> EvalRunDetailResponse:
    try:
        detail = await service.run(space_id=space_id)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalRunDetailResponse.from_domain(detail)


@router.get("/eval-runs/{run_id}", response_model=EvalRunDetailResponse)
async def get_evaluation_run(
    run_id: UUID,
    service: EvaluationServicePort = Depends(get_evaluation_service),
) -> EvalRunDetailResponse:
    try:
        detail = await service.get_run(run_id)
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalRunDetailResponse.from_domain(detail)


@router.patch("/eval-results/{result_id}", response_model=EvalResultResponse)
async def review_evaluation_result(
    result_id: UUID,
    payload: EvalResultReviewRequest,
    service: EvaluationServicePort = Depends(get_evaluation_service),
) -> EvalResultResponse:
    try:
        result = await service.review_result(
            result_id=result_id, **payload.model_dump()
        )
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    return EvalResultResponse.from_domain(result)
