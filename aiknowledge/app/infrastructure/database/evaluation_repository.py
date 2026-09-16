from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations import EvalCase, EvalResult, EvalRun
from app.infrastructure.database.models import (
    EvalCaseRecord,
    EvalResultRecord,
    EvalRunRecord,
    KnowledgeSpaceRecord,
)


class SqlAlchemyEvaluationRepository:
    """Durable adapter for lightweight evaluation sets, runs and reviews."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_active_space(self, space_id: UUID) -> bool:
        value = await self._session.scalar(
            select(KnowledgeSpaceRecord.id).where(
                KnowledgeSpaceRecord.id == space_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
        )
        return value is not None

    async def add_case(self, case: EvalCase) -> None:
        self._session.add(
            EvalCaseRecord(
                id=case.id,
                space_id=case.space_id,
                question=case.question,
                expected_answer=case.expected_answer,
                expected_document_ids=[str(value) for value in case.expected_document_ids],
                scope=case.scope,
                category_ids=[str(value) for value in case.category_ids],
                created_at=case.created_at,
            )
        )
        await self._session.flush()

    async def list_cases(self, space_id: UUID) -> list[EvalCase]:
        records = await self._session.scalars(
            select(EvalCaseRecord)
            .where(EvalCaseRecord.space_id == space_id)
            .order_by(EvalCaseRecord.created_at, EvalCaseRecord.id)
        )
        return [self._to_case(record) for record in records.all()]

    async def get_case(self, case_id: UUID) -> EvalCase | None:
        record = await self._session.get(EvalCaseRecord, case_id)
        return self._to_case(record) if record is not None else None

    async def update_case(self, case: EvalCase) -> None:
        record = await self._session.get(EvalCaseRecord, case.id)
        if record is None:
            return
        record.question = case.question
        record.expected_answer = case.expected_answer
        record.expected_document_ids = [str(value) for value in case.expected_document_ids]
        record.scope = case.scope
        record.category_ids = [str(value) for value in case.category_ids]
        await self._session.flush()

    async def delete_case(self, case_id: UUID) -> None:
        record = await self._session.get(EvalCaseRecord, case_id)
        if record is None:
            return
        await self._session.delete(record)
        await self._session.flush()

    async def add_run(self, run: EvalRun) -> None:
        self._session.add(
            EvalRunRecord(
                id=run.id,
                space_id=run.space_id,
                status=run.status,
                retrieval_config_snapshot=run.retrieval_config_snapshot,
                started_at=run.started_at,
                completed_at=run.completed_at,
                failure_message=run.failure_message,
                created_at=run.created_at,
            )
        )
        await self._session.flush()

    async def get_run(self, run_id: UUID) -> EvalRun | None:
        record = await self._session.get(EvalRunRecord, run_id)
        return self._to_run(record) if record is not None else None

    async def update_run(self, run: EvalRun) -> None:
        record = await self._session.get(EvalRunRecord, run.id)
        if record is None:
            return
        record.status = run.status
        record.retrieval_config_snapshot = run.retrieval_config_snapshot
        record.started_at = run.started_at
        record.completed_at = run.completed_at
        record.failure_message = run.failure_message
        await self._session.flush()

    async def add_result(self, result: EvalResult) -> None:
        self._session.add(
            EvalResultRecord(
                id=result.id,
                eval_run_id=result.eval_run_id,
                eval_case_id=result.eval_case_id,
                answer_status=result.answer_status,
                answer=result.answer,
                citation_count=result.citation_count,
                reviewer_score=result.reviewer_score,
                reviewer_note=result.reviewer_note,
            )
        )
        await self._session.flush()

    async def list_results(self, run_id: UUID) -> list[EvalResult]:
        records = await self._session.scalars(
            select(EvalResultRecord)
            .where(EvalResultRecord.eval_run_id == run_id)
            .order_by(EvalResultRecord.id)
        )
        return [self._to_result(record) for record in records.all()]

    async def get_result(self, result_id: UUID) -> EvalResult | None:
        record = await self._session.get(EvalResultRecord, result_id)
        return self._to_result(record) if record is not None else None

    async def update_result(self, result: EvalResult) -> None:
        record = await self._session.get(EvalResultRecord, result.id)
        if record is None:
            return
        record.reviewer_score = result.reviewer_score
        record.reviewer_note = result.reviewer_note
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    @staticmethod
    def _to_case(record: EvalCaseRecord) -> EvalCase:
        return EvalCase(
            id=record.id,
            space_id=record.space_id,
            question=record.question,
            expected_answer=record.expected_answer,
            expected_document_ids=tuple(UUID(value) for value in record.expected_document_ids),
            scope=record.scope,
            category_ids=tuple(UUID(value) for value in record.category_ids),
            created_at=record.created_at,
        )

    @staticmethod
    def _to_run(record: EvalRunRecord) -> EvalRun:
        return EvalRun(
            id=record.id,
            space_id=record.space_id,
            status=record.status,
            retrieval_config_snapshot=dict(record.retrieval_config_snapshot),
            created_at=record.created_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
            failure_message=record.failure_message,
        )

    @staticmethod
    def _to_result(record: EvalResultRecord) -> EvalResult:
        return EvalResult(
            id=record.id,
            eval_run_id=record.eval_run_id,
            eval_case_id=record.eval_case_id,
            answer_status=record.answer_status,
            answer=record.answer,
            citation_count=record.citation_count,
            reviewer_score=record.reviewer_score,
            reviewer_note=record.reviewer_note,
        )
