from __future__ import annotations

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

    async def create_case(self, **_kwargs: object) -> EvalCase:
        return self.case

    async def list_cases(self, _space_id: UUID) -> list[EvalCase]:
        return [self.case]

    async def update_case(self, _case_id: UUID, **_kwargs: object) -> EvalCase:
        return self.case

    async def delete_case(self, _case_id: UUID) -> None:
        return None

    async def run(self, *, space_id: UUID) -> EvaluationRunDetail:
        assert space_id == self.space_id
        return self._detail()

    async def get_run(self, _run_id: UUID) -> EvaluationRunDetail:
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
        run = await client.post(f"/api/v1/spaces/{service.space_id}/eval-runs")
        fetched = await client.get(f"/api/v1/eval-runs/{service.run_id}")
        reviewed = await client.patch(
            f"/api/v1/eval-results/{service.result_id}",
            json={"reviewer_score": 0.0, "reviewer_note": "越权回答。"},
        )

    assert created.status_code == 201
    assert listed.json()["items"][0]["scope"] == "OUT_OF_SCOPE"
    assert run.status_code == 201
    assert run.json()["run"]["retrieval_config_snapshot"]["chat_model"] == "deepseek-v4-flash"
    assert run.json()["summary"]["out_of_scope_violations"] == 1
    assert fetched.status_code == 200
    assert reviewed.status_code == 200
    assert reviewed.json()["reviewer_score"] == 0.0
    assert service.reviewed == (0.0, "越权回答。")
