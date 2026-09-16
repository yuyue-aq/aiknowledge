from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.conversations import (
    EvalCase,
    EvalResult,
    EvalRun,
    EvalRunStatus,
    EvalScope,
)
from app.domain.rag import AnswerStatus
from app.infrastructure.database.evaluation_repository import SqlAlchemyEvaluationRepository
from app.infrastructure.database.models import EvalCaseRecord, EvalResultRecord, EvalRunRecord


class FakeSession:
    def __init__(self) -> None:
        self.records: dict[type, dict[object, object]] = {}
        self.added: list[object] = []
        self.flushes = 0

    def add(self, record: object) -> None:
        self.added.append(record)
        self.records.setdefault(type(record), {})[record.id] = record  # type: ignore[attr-defined]

    async def get(self, model: type, record_id: object, **_: object) -> object | None:
        return self.records.get(model, {}).get(record_id)

    async def flush(self) -> None:
        self.flushes += 1


@pytest.mark.asyncio
async def test_evaluation_repository_persists_scope_snapshot_run_and_result() -> None:
    session = FakeSession()
    repository = SqlAlchemyEvaluationRepository(session)  # type: ignore[arg-type]
    now = datetime(2026, 9, 11, tzinfo=UTC)
    case = EvalCase(
        id=uuid4(),
        space_id=uuid4(),
        question="公开范围问题",
        expected_answer=None,
        expected_document_ids=(uuid4(),),
        scope=EvalScope.PUBLIC,
        category_ids=(uuid4(),),
        created_at=now,
    )
    run = EvalRun(
        id=uuid4(),
        space_id=case.space_id,
        status=EvalRunStatus.RUNNING,
        retrieval_config_snapshot={"chat_model": "deepseek-v4-flash"},
        created_at=now,
        started_at=now,
    )
    result = EvalResult(
        id=uuid4(),
        eval_run_id=run.id,
        eval_case_id=case.id,
        answer_status=AnswerStatus.OUT_OF_SCOPE,
        answer="当前资料中没有足够依据回答这个问题。",
        citation_count=0,
    )

    await repository.add_case(case)
    await repository.add_run(run)
    await repository.add_result(result)

    assert isinstance(session.added[0], EvalCaseRecord)
    assert session.added[0].scope is EvalScope.PUBLIC  # type: ignore[attr-defined]
    assert session.added[0].category_ids == [str(case.category_ids[0])]  # type: ignore[attr-defined]
    assert isinstance(session.added[1], EvalRunRecord)
    assert isinstance(session.added[2], EvalResultRecord)
    assert session.added[2].answer_status is AnswerStatus.OUT_OF_SCOPE  # type: ignore[attr-defined]
    assert await repository.get_case(case.id) == case
    assert await repository.get_run(run.id) == run
    assert await repository.get_result(result.id) == result
    assert session.flushes == 3
