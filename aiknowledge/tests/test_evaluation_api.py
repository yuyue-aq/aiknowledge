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


def test_feedback_regression_api_requires_explicit_human_confirmation():
    import pytest
    from pydantic import ValidationError
    from app.api.v1.evaluations import EvalCaseFromFeedbackRequest

    payload = EvalCaseFromFeedbackRequest(
        source_feedback_confirmed=True,
        expected_answer='人工核对的标准答案',
        scope='OWNER',
        answerable=True,
        expected_behavior='ANSWERED',
    )
    assert payload.source_feedback_confirmed is True
    with pytest.raises(ValidationError):
        EvalCaseFromFeedbackRequest(expected_answer='答案', scope='OWNER')


def test_summary_keeps_unlabeled_unknown_and_reports_manual_scoring_coverage():
    from dataclasses import replace
    from app.api.v1.evaluations import _summary
    from app.domain.conversations import EvaluationRunDetail, EvalResult
    service = FakeEvaluationService()
    detail = service._detail()
    first = replace(detail.results[0], reviewer_score=1., retrieval_metrics={'document_recall_at_k': .5, 'document_hit_at_k': 1.},
        model_grade_suggestions=({'status': 'SUCCEEDED', 'suggested_score': 1.},))
    second = replace(first, id=uuid4(), reviewer_score=.5, retrieval_metrics=None,
        model_grade_suggestions=({'status': 'SUCCEEDED', 'suggested_score': 0.},))
    third = replace(first, id=uuid4(), reviewer_score=None, retrieval_metrics=None,
        model_grade_suggestions=({'status': 'FAILED', 'suggested_score': None},))
    summary = _summary(EvaluationRunDetail(detail.run, (first, second, third), detail.cases_by_id))
    assert summary.document_recall_at_k == .5
    assert summary.retrieval_measured_count == 1
    assert summary.answer_accuracy == .5
    assert summary.reviewed_coverage == 2/3
    assert summary.model_suggestion_coverage == 2/3
    assert summary.model_human_overlap_count == 2
    assert summary.model_human_agreement_rate == .5
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
from app.api.dependencies import get_current_user


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
        self.grade_suggestion_user_id = None
        self.run_kwargs = None
        self.feedback_case_kwargs = None
        self.impact_user_id = None
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

    async def create_case_from_feedback(self, **kwargs: object) -> EvalCase:
        self.feedback_case_kwargs = kwargs
        return replace(self.case, source_feedback_id=kwargs['feedback_id'])

    async def list_cases(self, _space_id: UUID) -> list[EvalCase]:
        return [self.case]

    async def get_knowledge_impact(self, _space_id: UUID, **kwargs):
        self.impact_user_id = kwargs.get('owner_user_id')
        return {
            'stale_case_count': 0,
            'stale_evidence_count': 0,
            'stale_cases': [],
            'updated_citation_count': 0,
            'updated_citations': [],
            'updated_citations_truncated': False,
            'answer_classification': None,
        }

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
        self.result = replace(
            self.result,
            reviewer_score=reviewer_score,
            reviewer_note=reviewer_note,
        )
        return self.result

    async def suggest_result_grade(self, *, result_id: UUID, owner_user_id: UUID | None = None) -> EvalResult:
        assert result_id == self.result_id
        self.grade_suggestion_user_id = owner_user_id
        self.result = replace(self.result, model_grade_suggestions=(*self.result.model_grade_suggestions, {
            'id': str(uuid4()), 'status': 'SUCCEEDED', 'model': 'deepseek-flash',
            'prompt_version': 'eval-judge-v1', 'suggested_score': 0.5,
            'rationale': '主要事实正确，但遗漏一项。', 'failure_code': None,
            'created_at': self.now.isoformat(), 'prompt_tokens': 100, 'completion_tokens': 30,
        }))
        return self.result

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
        suggested = await client.post(f"/api/v1/eval-results/{service.result_id}/model-grade")

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
    assert suggested.status_code == 200
    assert suggested.json()["model_grade_suggestions"][0]["suggested_score"] == 0.5
    assert suggested.json()["reviewer_score"] == 0.0


@pytest.mark.asyncio
async def test_knowledge_impact_requires_authenticated_admin_and_returns_typed_report():
    from types import SimpleNamespace

    service = FakeEvaluationService()
    app = create_app(rag_service=object(), evaluation_service_factory=lambda _: service)
    user_id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://testserver'
    ) as client:
        response = await client.get(f'/api/v1/spaces/{service.space_id}/knowledge-impact')

    assert response.status_code == 200
    assert response.json()['stale_case_count'] == 0
    assert service.impact_user_id == user_id


@pytest.mark.asyncio
async def test_evaluation_api_creates_feedback_regression_case_with_explicit_confirmation():
    service = FakeEvaluationService()
    app = create_app(rag_service=object(), evaluation_service_factory=lambda _: service)
    feedback_id = uuid4()
    evidence = {
        "document_id": str(uuid4()),
        "document_version_id": str(uuid4()),
        "source_block_id": "block-1",
        "char_start": 0,
        "char_end": 3,
        "text_hash": "a" * 64,
        "required": True,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            f"/api/v1/spaces/{service.space_id}/eval-cases/from-feedback/{feedback_id}",
            json={
                "source_feedback_confirmed": True,
                "expected_answer": "人工核对后的标准答案",
                "scope": "OWNER",
                "answerable": True,
                "expected_behavior": "ANSWERED",
                "evidence_refs": [evidence],
            },
        )

    assert created.status_code == 201
    assert created.json()["source_feedback_id"] == str(feedback_id)
    assert service.feedback_case_kwargs["source_feedback_confirmed"] is True
    assert len(service.feedback_case_kwargs["evidence_refs"]) == 1
