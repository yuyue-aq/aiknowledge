from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.retrieval import RetrievalRun, RetrievalScope
from app.domain.users import SpaceRole
from app.domain.spaces import SpaceKind
from app.infrastructure.database.conversation_repository import SqlAlchemyConversationRepository
from app.infrastructure.database.models import ChunkRecord, DocumentRecord, DocumentVersionRecord, KnowledgeSpaceRecord, RetrievalRunRecord, SpaceMembershipRecord
from app.infrastructure.database.document_repository import SqlAlchemyDocumentRepository


class SqlAlchemyRetrievalRepository:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._conversations = SqlAlchemyConversationRepository(session)

    async def resolve_owner_scope(self, *, space_id: UUID, user_id: UUID) -> RetrievalScope | None:
        result = await self._session.execute(select(
            KnowledgeSpaceRecord.id, KnowledgeSpaceRecord.access_revision, KnowledgeSpaceRecord.knowledge_revision
        ).where(
            KnowledgeSpaceRecord.id == space_id,
            KnowledgeSpaceRecord.deleted_at.is_(None),
            or_(KnowledgeSpaceRecord.owner_user_id == user_id, exists(select(SpaceMembershipRecord.space_id).where(
                SpaceMembershipRecord.space_id == KnowledgeSpaceRecord.id,
                SpaceMembershipRecord.user_id == user_id,
                or_(SpaceMembershipRecord.role == SpaceRole.OWNER,
                    and_(KnowledgeSpaceRecord.kind == SpaceKind.TEAM,
                         SpaceMembershipRecord.role == SpaceRole.ADMIN)),
            ))),
        ))
        row = result.first()
        if row is None:
            return None
        return RetrievalScope(row.id, user_id, row.access_revision, row.knowledge_revision, datetime.now(UTC))

    async def retrieve(self, *, scope: RetrievalScope, embedding: list[float], limit: int):
        return await self._conversations.retrieve_owner(space_id=scope.space_id, embedding=embedding, limit=limit)

    async def keyword_corpus(self, *, scope: RetrievalScope, limit: int):
        statement=self._conversations._base_retrieval_statement(None).where(
            ChunkRecord.space_id==scope.space_id).order_by(None).order_by(ChunkRecord.id).limit(limit)
        rows=await self._session.execute(statement)
        return self._conversations._map_retrieval_rows(rows.all())

    async def get_current_chunks(self, *, scope: RetrievalScope, chunk_ids: tuple[UUID, ...]):
        if not chunk_ids:
            return []
        # Reuse the complete live eligibility predicate, including expiry; an ID
        # by itself never grants access to historical or deleted raw evidence.
        statement = self._conversations._base_retrieval_statement(None).where(
            ChunkRecord.space_id == scope.space_id, ChunkRecord.id.in_(chunk_ids)
        ).order_by(None)
        rows = await self._session.execute(statement)
        return self._conversations._map_retrieval_rows(rows.all())

    async def get_document_detail(self, *, scope: RetrievalScope, document_id: UUID):
        document = await self._session.scalar(select(DocumentRecord).where(DocumentRecord.id == document_id,
            DocumentRecord.space_id == scope.space_id, DocumentRecord.deleted_at.is_(None)))
        if document is None:
            return None
        versions = (await self._session.scalars(select(DocumentVersionRecord).where(
            DocumentVersionRecord.document_id == document_id).order_by(DocumentVersionRecord.version_number.desc()))).all()
        statement = self._conversations._base_retrieval_statement(None).where(
            ChunkRecord.space_id == scope.space_id, ChunkRecord.document_id == document_id).order_by(None).order_by(ChunkRecord.ordinal)
        chunks = self._conversations._map_retrieval_rows((await self._session.execute(statement)).all())
        return {'document': SqlAlchemyDocumentRepository._to_document(document),
            'versions': [SqlAlchemyDocumentRepository._to_version(item) for item in versions], 'chunks': chunks}

    async def add_run(self, run: RetrievalRun) -> None:
        self._session.add(RetrievalRunRecord(
            id=run.id, space_id=run.scope.space_id, user_id=run.scope.user_id,
            access_revision=run.scope.access_revision, knowledge_revision=run.scope.knowledge_revision,
            resolved_at=run.scope.resolved_at, question=run.question, top_k=run.top_k,
            chunk_ids=[str(x) for x in run.chunk_ids], scores=list(run.scores),
            timings_ms=dict(run.timings_ms), model_name=run.model_name, created_at=run.created_at,
            strategy=run.strategy, config_snapshot=dict(run.config_snapshot),
        ))
        await self._session.flush()

    async def get_run(self, run_id: UUID) -> RetrievalRun | None:
        row = await self._session.get(RetrievalRunRecord, run_id)
        if row is None:
            return None
        return RetrievalRun(row.id, RetrievalScope(row.space_id, row.user_id, row.access_revision,
            row.knowledge_revision, row.resolved_at), row.question, row.top_k, tuple(UUID(x) for x in row.chunk_ids),
            tuple(row.scores), dict(row.timings_ms), row.model_name, row.created_at,row.strategy,dict(row.config_snapshot))
