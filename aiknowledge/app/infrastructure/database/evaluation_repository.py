from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import exists, or_, select, update, func, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations import (
    EvalCase,
    EvalFeedbackAlreadyLinkedError,
    EvalResult,
    EvalRun,
    EvalRunStatus,
    EvalScope,
    EvalSetVersion,
    FeedbackRegressionSource,
)
from app.infrastructure.database.models import (
    EvalCaseRecord,
    EvalResultRecord,
    EvalRunRecord,
    EvalSetVersionRecord,
    FeedbackRecord,
    ConversationRecord,
    KnowledgeSpaceRecord,
    MessageRecord,
    RagRunRecord,
    SpaceMembershipRecord,
    share_link_categories,
)
from app.domain.users import SpaceRole
from app.domain.evaluation import EvidenceRef
from app.infrastructure.database.models import ChunkRecord, DocumentRecord
from app.infrastructure.database.conversation_repository import SqlAlchemyConversationRepository
from app.services.evaluation_metrics import evidence_coverage
from app.services.evaluation_snapshot import knowledge_manifest
from app.infrastructure.database.models import DocumentVersionRecord
from app.infrastructure.database.feedback_repository import original_feedback_question_expression


class SqlAlchemyEvaluationRepository:
    """Durable adapter for lightweight evaluation sets, runs and reviews."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_space_access(self, *, space_id: UUID, user_id: UUID) -> bool:
        value = await self._session.scalar(
            select(KnowledgeSpaceRecord.id).where(
                KnowledgeSpaceRecord.id == space_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
                or_(
                    KnowledgeSpaceRecord.owner_user_id == user_id,
                    exists(
                        select(SpaceMembershipRecord.space_id).where(
                            SpaceMembershipRecord.space_id == KnowledgeSpaceRecord.id,
                            SpaceMembershipRecord.user_id == user_id,
                        )
                    ),
                ),
            )
        )
        return value is not None

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        space = await self._session.scalar(
            select(KnowledgeSpaceRecord).where(
                KnowledgeSpaceRecord.id == space_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
        )
        if space is None:
            return None
        if space.owner_user_id == user_id:
            return SpaceRole.OWNER
        return await self._session.scalar(
            select(SpaceMembershipRecord.role).where(
                SpaceMembershipRecord.space_id == space_id,
                SpaceMembershipRecord.user_id == user_id,
            )
        )

    async def has_active_space(self, space_id: UUID) -> bool:
        value = await self._session.scalar(
            select(KnowledgeSpaceRecord.id).where(
                KnowledgeSpaceRecord.id == space_id,
                KnowledgeSpaceRecord.deleted_at.is_(None),
            )
        )
        return value is not None

    async def add_case(self, case: EvalCase) -> None:
        values = {
            "id": case.id,
            "space_id": case.space_id,
            "source_feedback_id": case.source_feedback_id,
            "question": case.question,
            "expected_answer": case.expected_answer,
            "expected_document_ids": [str(value) for value in case.expected_document_ids],
            "scope": case.scope,
            "category_ids": [str(value) for value in case.category_ids],
            "created_at": case.created_at,
            "answerable": case.answerable,
            "expected_behavior": case.expected_behavior,
            "evidence_refs": [ref.to_dict() for ref in case.evidence_refs],
        }
        if case.source_feedback_id is None:
            self._session.add(EvalCaseRecord(**values))
            await self._session.flush()
            return

        statement = (
            pg_insert(EvalCaseRecord)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_eval_cases_source_feedback_id")
            .returning(EvalCaseRecord.id)
        )
        result = await self._session.execute(statement)
        if result.scalar_one_or_none() is None:
            raise EvalFeedbackAlreadyLinkedError("这条反馈已经加入回归题集。")

    async def get_feedback_regression_source(
        self, feedback_id: UUID
    ) -> FeedbackRegressionSource | None:
        original_question = original_feedback_question_expression()
        result = await self._session.execute(
            select(
                FeedbackRecord,
                ConversationRecord.space_id,
                ConversationRecord.share_link_id,
                original_question,
            )
            .select_from(FeedbackRecord)
            .join(MessageRecord, FeedbackRecord.message_id == MessageRecord.id)
            .outerjoin(RagRunRecord, RagRunRecord.message_id == MessageRecord.id)
            .join(ConversationRecord, MessageRecord.conversation_id == ConversationRecord.id)
            .where(FeedbackRecord.id == feedback_id)
            .with_for_update(of=FeedbackRecord)
        )
        row = result.one_or_none()
        if row is None:
            return None
        feedback, space_id, share_link_id, question = row
        if not isinstance(question, str) or not question.strip():
            return None

        category_ids: tuple[UUID, ...] = ()
        if feedback.is_guest and share_link_id is not None:
            categories = await self._session.scalars(
                select(share_link_categories.c.category_id)
                .where(share_link_categories.c.share_link_id == share_link_id)
                .order_by(share_link_categories.c.category_id)
            )
            category_ids = tuple(categories.all())
        linked_case_id = await self._session.scalar(
            select(EvalCaseRecord.id).where(EvalCaseRecord.source_feedback_id == feedback_id)
        )
        return FeedbackRegressionSource(
            feedback_id=feedback_id,
            space_id=space_id,
            question=question.strip(),
            corrected_answer=feedback.corrected_answer,
            is_guest=feedback.is_guest,
            review_status=feedback.review_status,
            category_ids=category_ids,
            linked_eval_case_id=linked_case_id,
        )

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
        record.answerable = case.answerable
        record.expected_behavior = case.expected_behavior
        record.evidence_refs = [ref.to_dict() for ref in case.evidence_refs]
        await self._session.flush()

    async def delete_case(self, case_id: UUID) -> None:
        record = await self._session.get(EvalCaseRecord, case_id)
        if record is None:
            return
        await self._session.delete(record)
        await self._session.flush()

    async def has_results_for_case(self, case_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                select(exists().where(EvalResultRecord.eval_case_id == case_id))
            )
        )

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
                **{name: getattr(run, name) for name in ('progress_total', 'progress_completed', 'heartbeat_at', 'lease_owner', 'lease_expires_at', 'task_id', 'failure_code')},
            )
        )
        await self._session.flush()

    async def get_run(self, run_id: UUID) -> EvalRun | None:
        record = await self._session.get(EvalRunRecord, run_id, populate_existing=True)
        return self._to_run(record) if record is not None else None

    async def list_runs(self, space_id: UUID, limit: int = 20) -> list[EvalRun]:
        records = await self._session.scalars(
            select(EvalRunRecord)
            .where(EvalRunRecord.space_id == space_id)
            .order_by(EvalRunRecord.created_at.desc(), EvalRunRecord.id.desc())
            .limit(limit)
        )
        return [self._to_run(record) for record in records.all()]

    async def add_version(self, version: EvalSetVersion) -> None:
        self._session.add(
            EvalSetVersionRecord(
                id=version.id,
                space_id=version.space_id,
                version_number=version.version_number,
                label=version.label,
                cases_snapshot=[self._case_to_dict(case) for case in version.cases],
                created_at=version.created_at,
            )
        )
        await self._session.flush()

    async def list_versions(self, space_id: UUID, limit: int = 20) -> list[EvalSetVersion]:
        records = await self._session.scalars(
            select(EvalSetVersionRecord)
            .where(EvalSetVersionRecord.space_id == space_id)
            .order_by(EvalSetVersionRecord.version_number.desc())
            .limit(limit)
        )
        return [self._to_version(record) for record in records.all()]

    async def get_version(self, version_id: UUID) -> EvalSetVersion | None:
        record = await self._session.get(EvalSetVersionRecord, version_id)
        return self._to_version(record) if record is not None else None

    async def update_run(self, run: EvalRun) -> None:
        record = await self._session.get(EvalRunRecord, run.id)
        if record is None:
            return
        record.status = run.status
        record.retrieval_config_snapshot = run.retrieval_config_snapshot
        record.started_at = run.started_at
        record.completed_at = run.completed_at
        record.failure_message = run.failure_message
        for name in ('progress_total', 'progress_completed', 'heartbeat_at', 'lease_owner', 'lease_expires_at', 'task_id', 'failure_code'):
            setattr(record, name, getattr(run, name))
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
                execution_snapshot=result.execution_snapshot,
                retrieval_metrics=result.retrieval_metrics,
                failure_code=result.failure_code,
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

    async def rollback(self):
        await self._session.rollback()

    async def capture_knowledge_manifest(self, space_id: UUID):
        revision_query = select(KnowledgeSpaceRecord.access_revision, KnowledgeSpaceRecord.knowledge_revision).where(
            KnowledgeSpaceRecord.id == space_id, KnowledgeSpaceRecord.deleted_at.is_(None))
        before = (await self._session.execute(revision_query)).first()
        if before is None:
            raise ValueError('空间已不可用。')
        statement = SqlAlchemyConversationRepository._base_retrieval_statement(None).join(
            DocumentVersionRecord, DocumentVersionRecord.id == ChunkRecord.document_version_id
        ).where(ChunkRecord.space_id == space_id).with_only_columns(
            ChunkRecord.id, ChunkRecord.document_id, ChunkRecord.document_version_id, ChunkRecord.content_hash,
            ChunkRecord.source_block_id, ChunkRecord.char_start, ChunkRecord.char_end, ChunkRecord.token_count,
            DocumentRecord.sha256, DocumentVersionRecord.parser_version, DocumentVersionRecord.chunk_config,
            DocumentVersionRecord.embedding_model, DocumentVersionRecord.embedding_dimension,
        ).order_by(ChunkRecord.id)
        rows = (await self._session.execute(statement)).all()
        after = (await self._session.execute(revision_query)).first()
        if before != after:
            raise ValueError('资料正在变化，请稍后再创建运行。')
        chunks = [{
            'chunk_id': str(row.id), 'document_id': str(row.document_id), 'document_version_id': str(row.document_version_id),
            'content_hash': row.content_hash, 'source_hash': row.sha256, 'source_block_id': row.source_block_id,
            'char_start': row.char_start, 'char_end': row.char_end, 'token_count': row.token_count,
            'parser_version': row.parser_version, 'chunk_config': row.chunk_config,
            'embedding_model': row.embedding_model, 'embedding_dimension': row.embedding_dimension,
        } for row in rows]
        return knowledge_manifest(chunks, access_revision=before.access_revision, knowledge_revision=before.knowledge_revision)

    async def list_recoverable_runs(self, *, limit: int = 20):
        statement = select(EvalRunRecord.id).where(or_(
            and_(EvalRunRecord.status == EvalRunStatus.PENDING,
                EvalRunRecord.created_at < func.clock_timestamp()-timedelta(minutes=5)),
            and_(EvalRunRecord.status == EvalRunStatus.RUNNING, or_(EvalRunRecord.lease_expires_at.is_(None),
                EvalRunRecord.lease_expires_at < func.clock_timestamp())),
        )).order_by(EvalRunRecord.created_at).limit(max(1, min(limit, 100)))
        return list((await self._session.scalars(statement)).all())

    async def mark_dispatch_failure(self, run_id: UUID):
        await self._session.execute(update(EvalRunRecord).where(EvalRunRecord.id == run_id,
            EvalRunRecord.status == EvalRunStatus.PENDING).values(failure_code='QUEUE_UNAVAILABLE',
            failure_message='评测队列暂不可用，可稍后补投此任务。'))
        return await self.get_run(run_id)

    async def prepare_redispatch(self, run_id: UUID):
        statement = update(EvalRunRecord).where(EvalRunRecord.id == run_id, or_(
            EvalRunRecord.status.in_([EvalRunStatus.PENDING, EvalRunStatus.FAILED]),
            and_(EvalRunRecord.status == EvalRunStatus.RUNNING, or_(EvalRunRecord.lease_expires_at.is_(None),
                EvalRunRecord.lease_expires_at < func.clock_timestamp())),
        )).values(status=EvalRunStatus.PENDING, lease_owner=None, lease_expires_at=None,
            failure_code=None, failure_message=None, completed_at=None).returning(EvalRunRecord).execution_options(populate_existing=True)
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return self._to_run(row) if row is not None else None

    async def claim_run(self, run_id: UUID, *, lease_token: str, lease_seconds: int):
        statement = update(EvalRunRecord).where(EvalRunRecord.id == run_id, or_(
            EvalRunRecord.status == EvalRunStatus.PENDING,
            EvalRunRecord.status == EvalRunStatus.FAILED,
            and_(EvalRunRecord.status == EvalRunStatus.RUNNING, or_(EvalRunRecord.lease_expires_at.is_(None),
                EvalRunRecord.lease_expires_at < func.clock_timestamp())),
        )).values(status=EvalRunStatus.RUNNING, lease_owner=lease_token,
            lease_expires_at=func.clock_timestamp()+timedelta(seconds=lease_seconds), heartbeat_at=func.clock_timestamp(),
            started_at=func.coalesce(EvalRunRecord.started_at, func.clock_timestamp()),
            failure_code=None, failure_message=None, completed_at=None,
        ).returning(EvalRunRecord).execution_options(populate_existing=True)
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return self._to_run(row) if row is not None else None

    async def checkpoint_result(self, result: EvalResult, *, lease_token: str, lease_seconds: int) -> bool:
        lease = update(EvalRunRecord).where(EvalRunRecord.id == result.eval_run_id,
            EvalRunRecord.status == EvalRunStatus.RUNNING, EvalRunRecord.lease_owner == lease_token,
            EvalRunRecord.lease_expires_at > func.clock_timestamp()).values(
                heartbeat_at=func.clock_timestamp(), lease_expires_at=func.clock_timestamp()+timedelta(seconds=lease_seconds)
            ).returning(EvalRunRecord.id)
        if (await self._session.execute(lease)).scalar_one_or_none() is None:
            return False
        await self._session.execute(pg_insert(EvalResultRecord).values(
            id=result.id, eval_run_id=result.eval_run_id, eval_case_id=result.eval_case_id,
            answer_status=result.answer_status, answer=result.answer, citation_count=result.citation_count,
            execution_snapshot=result.execution_snapshot, retrieval_metrics=result.retrieval_metrics,
            failure_code=result.failure_code,
        ).on_conflict_do_nothing(constraint='uq_eval_results_run_case'))
        await self._session.execute(update(EvalRunRecord).where(EvalRunRecord.id == result.eval_run_id,
            EvalRunRecord.lease_owner == lease_token).values(progress_completed=select(func.count(EvalResultRecord.id)).where(
                EvalResultRecord.eval_run_id == result.eval_run_id).scalar_subquery()))
        return True

    async def finish_run(self, run: EvalRun, *, lease_token: str) -> bool:
        statement = update(EvalRunRecord).where(EvalRunRecord.id == run.id,
            EvalRunRecord.status == EvalRunStatus.RUNNING, EvalRunRecord.lease_owner == lease_token,
            EvalRunRecord.lease_expires_at > func.clock_timestamp()).values(status=run.status,
                progress_completed=run.progress_completed, heartbeat_at=func.clock_timestamp(),
                completed_at=run.completed_at, failure_code=run.failure_code, failure_message=run.failure_message,
                lease_owner=None, lease_expires_at=None).returning(EvalRunRecord.id)
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def validate_case_evidence(self, *, space_id: UUID, expected_document_ids, evidence_refs):
        doc_ids = set(expected_document_ids) | {ref.document_id for ref in evidence_refs}
        if not doc_ids:
            return True
        actual = await self._session.scalars(select(DocumentRecord.id).where(DocumentRecord.space_id == space_id,
            DocumentRecord.id.in_(doc_ids), DocumentRecord.deleted_at.is_(None)))
        if set(actual.all()) != doc_ids:
            return False
        if not evidence_refs:
            return True
        statement = SqlAlchemyConversationRepository._base_retrieval_statement(None).where(
            ChunkRecord.space_id == space_id, ChunkRecord.document_id.in_(doc_ids)).order_by(None)
        rows = (await self._session.execute(statement)).all()
        chunks = SqlAlchemyConversationRepository._map_retrieval_rows(rows)
        return all(evidence_coverage(ref, chunks)[1] for ref in evidence_refs)

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
            answerable=record.answerable,
            expected_behavior=record.expected_behavior,
            evidence_refs=tuple(EvidenceRef.from_dict(ref) for ref in (record.evidence_refs or [])),
            source_feedback_id=record.source_feedback_id,
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
            **{name: getattr(record, name) for name in ('progress_total', 'progress_completed', 'heartbeat_at', 'lease_owner', 'lease_expires_at', 'task_id', 'failure_code')},
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
            execution_snapshot=record.execution_snapshot,
            retrieval_metrics=record.retrieval_metrics,
            failure_code=record.failure_code,
        )

    @staticmethod
    def _case_to_dict(case: EvalCase) -> dict[str, object]:
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
            'source_feedback_id': str(case.source_feedback_id) if case.source_feedback_id else None,
        }

    @classmethod
    def _to_version(cls, record: EvalSetVersionRecord) -> EvalSetVersion:
        return EvalSetVersion(
            id=record.id,
            space_id=record.space_id,
            version_number=record.version_number,
            label=record.label,
            cases=tuple(cls._case_from_dict(item) for item in (record.cases_snapshot or [])),
            created_at=record.created_at,
        )

    @staticmethod
    def _case_from_dict(item: dict[str, object]) -> EvalCase:
        created_at = datetime.fromisoformat(str(item["created_at"]))
        return EvalCase(
            id=UUID(str(item["id"])),
            space_id=UUID(str(item["space_id"])),
            question=str(item["question"]),
            expected_answer=(
                str(item["expected_answer"])
                if item.get("expected_answer") is not None
                else None
            ),
            expected_document_ids=tuple(UUID(str(value)) for value in item.get("expected_document_ids", [])),
            scope=EvalScope(str(item["scope"])),
            category_ids=tuple(UUID(str(value)) for value in item.get("category_ids", [])),
            created_at=created_at,
            answerable=item.get('answerable'),
            expected_behavior=item.get('expected_behavior'),
            evidence_refs=tuple(EvidenceRef.from_dict(ref) for ref in item.get('evidence_refs', [])),
            source_feedback_id=(
                UUID(str(item['source_feedback_id']))
                if item.get('source_feedback_id') is not None
                else None
            ),
        )
