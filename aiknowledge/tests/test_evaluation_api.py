from __future__ import annotations


def test_eval_case_api_accepts_typed_evidence_and_rejects_invalid_intervals():
    import pytest
    from uuid import uuid4
    from pydantic import ValidationError
    from app.api.v1.evaluations import EvalCaseCreateRequest
    ref = {'document_id': str(uuid4()), 'document_version_id': str(uuid4()), 'source_block_id': 'block-1',
           'char_start': 0, 'char_end': 3, 'text_hash': 'a'*64, 'required': True}
    payload = EvalCaseCreateRequest(question='问题', answerable=True, expected_behavior='ANSWERED', evidence_refs=[ref])
    assert payload.answerable is True
    assert payload.evidence_refs[0].char_end == 3
    with pytest.raises(ValidationError):
        EvalCaseCreateRequest(question='问题', evidence_refs=[{**ref, 'char_end': 0}])


def test_summary_keeps_unlabeled_unknown_and_reports_manual_scoring_coverage():
    from dataclasses import replace
    from app.api.v1.evaluations import _summary
    from app.domain.conversations import EvaluationRunDetail, EvalResult
    service = FakeEvaluationService()
    detail = service._detail()
    first = replace(detail.results[0], reviewer_score=1., retrieval_metrics={'document_recall_at_k': .5, 'document_hit_at_k': 1.})
    second = replace(first, id=uuid4(), reviewer_score=.5, retrieval_metrics=None)
    third = replace(first, id=uuid4(), reviewer_score=None, retrieval_metrics=None)
    summary = _summary(EvaluationRunDetail(detail.run, (first, second, third), detail.cases_by_id))
    assert summary.document_recall_at_k == .5
    assert summary.retrieval_measured_count == 1
    assert summary.answer_accuracy == .5
    assert summary.reviewed_coverage == 2/3
    empty = _summary(EvaluationRunDetail(detail.run, (), detail.cases_by_id))
    assert empty.document_recall_at_k is None
    assert empty.answer_accuracy is None

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain.conversations import (
    EvalCase,
    EvalResult,
    EvalRun,
    EvalRunStatus,
    EvalScope,
    EvalSetVersion,
    EvaluationRunComparison,
    EvaluationRunDetail,
)
from app.domain.rag import AnswerStatus
from app.main import create_app


class FakeEvaluationService:
    def __init__(self) -> None:
        self.space_id = uuid4()
        self.category_id = uuid4()
        self.case_id = uuid4()
        self.run_id = uuid4()
        self.result_id = uuid4()
        self.now = datetime(2026, 9, 11, tzinfo=UTC)
        self.case = EvalCase(
            id=self.case_id,
            space_id=self.space_id,
            question="公开范围问题",
            expected_answer=None,
            expected_document_ids=(),
            scope=EvalScope.OUT_OF_SCOPE,
            category_ids=(self.category_id,),
            created_at=self.now,
        )
        self.result = EvalResult(
            id=self.result_id,
            eval_run_id=self.run_id,
            eval_case_id=self.case_id,
            answer_status=AnswerStatus.ANSWERED,
            answer="错误地回答了越权问题。",
            citation_count=1,
        )
        self.run_record = EvalRun(
            id=self.run_id,
            space_id=self.space_id,
            status=EvalRunStatus.COMPLETED,
            retrieval_config_snapshot={"chat_model": "deepseek-v4-flash"},
            created_at=self.now,
            started_at=self.now,
            completed_at=self.now,
        )
        self.reviewed = None
        self.run_kwargs = None
        self.version = EvalSetVersion(
            id=uuid4(),
            space_id=self.space_id,
            version_number=1,
            label="基线版本",
            cases=(self.case,),
            created_at=self.now,
        )

    async def create_case(self, **_kwargs: object) -> EvalCase:
        return self.case

    async def list_cases(self, _space_id: UUID) -> list[EvalCase]:
        return [self.case]

    async def update_case(self, _case_id: UUID, **_kwargs: object) -> EvalCase:
        return self.case

    async def delete_case(self, _case_id: UUID) -> None:
        return None

    async def run(self, *, space_id: UUID, **kwargs: object) -> EvaluationRunDetail:
        assert space_id == self.space_id
        self.run_kwargs = kwargs
        return self._detail()

    async def get_run(self, _run_id: UUID) -> EvaluationRunDetail:
        return self._detail()

    async def compare_runs(self, **_kwargs: object) -> EvaluationRunComparison:
        return EvaluationRunComparison(baseline=self._detail(), candidate=self._detail())

    async def list_runs(self, _space_id: UUID, **_: object) -> list[EvalRun]:
        return [self.run_record]

    async def create_version(self, **_kwargs: object) -> EvalSetVersion:
        return self.version

    async def list_versions(self, _space_id: UUID, **_: object) -> list[EvalSetVersion]:
        return [self.version]

    async def get_version(self, _version_id: UUID, **_: object) -> EvalSetVersion:
        return self.version

    async def run_version(self, _version_id: UUID, **_: object) -> EvaluationRunDetail:
        return self._detail()

    async def review_result(
        self, *, result_id: UUID, reviewer_score: float, reviewer_note: str | None
    ) -> EvalResult:
        assert result_id == self.result_id
        self.reviewed = (reviewer_score, reviewer_note)
        return replace(
            self.result,
            reviewer_score=reviewer_score,
            reviewer_note=reviewer_note,
        )

    def _detail(self) -> EvaluationRunDetail:
        return EvaluationRunDetail(
            run=self.run_record,
            results=(self.result,),
            cases_by_id={self.case.id: self.case},
        )


@pytest.mark.asyncio
async def test_evaluation_api_exposes_cases_run_snapshot_security_summary_and_manual_review() -> None:
    service = FakeEvaluationService()
    app = create_app(
        rag_service=object(), evaluation_service_factory=lambda _: service
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/api/v1/spaces/{service.space_id}/eval-cases",
            json={
                "question": "公开范围问题",
                "scope": "OUT_OF_SCOPE",
                "category_ids": [str(service.category_id)],
            },
        )
        listed = await client.get(f"/api/v1/spaces/{service.space_id}/eval-cases")
        run = await client.post(
            f"/api/v1/spaces/{service.space_id}/eval-runs",
            json={"metadata_filter": {"formats": ["pdf"], "version_min": 2}},
        )
        fetched = await client.get(f"/api/v1/eval-runs/{service.run_id}")
        history = await client.get(f"/api/v1/spaces/{service.space_id}/eval-runs")
        compared = await client.get(
            f"/api/v1/spaces/{service.space_id}/eval-runs/compare",
            params={
                "baseline_run_id": str(service.run_id),
                "candidate_run_id": str(uuid4()),
            },
        )
        version_created = await client.post(
            f"/api/v1/spaces/{service.space_id}/eval-versions", json={"label": "基线版本"}
        )
        versions = await client.get(f"/api/v1/spaces/{service.space_id}/eval-versions")
        version_detail = await client.get(f"/api/v1/eval-versions/{service.version.id}")
        version_run = await client.post(f"/api/v1/eval-versions/{service.version.id}/runs")
        reviewed = await client.patch(
            f"/api/v1/eval-results/{service.result_id}",
            json={"reviewer_score": 0.0, "reviewer_note": "越权回答。"},
        )

    assert created.status_code == 201
    assert listed.json()["items"][0]["scope"] == "OUT_OF_SCOPE"
    assert run.status_code == 201
    assert run.json()["run"]["retrieval_config_snapshot"]["chat_model"] == "deepseek-v4-flash"
    assert service.run_kwargs["metadata_filter"].formats == ("pdf",)
    assert service.run_kwargs["metadata_filter"].version_min == 2
    assert run.json()["summary"]["out_of_scope_violations"] == 1
    assert fetched.status_code == 200
    assert history.status_code == 200
    assert history.json()["items"][0]["id"] == str(service.run_id)
    assert compared.status_code == 200
    assert compared.json()["baseline_summary"]["out_of_scope_violations"] == 1
    assert compared.json()["delta"]["answered_rate"] == 0.0
    assert version_created.status_code == 201
    assert version_created.json()["version_number"] == 1
    assert versions.status_code == 200
    assert version_detail.json()["cases"][0]["question"] == "公开范围问题"
    assert version_run.status_code == 201
    assert reviewed.status_code == 200
    assert reviewed.json()["reviewer_score"] == 0.0
    assert service.reviewed == (0.0, "越权回答。")
