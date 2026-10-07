from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.conversations import RetrievedChunk
from app.domain.retrieval import RetrievalError, RetrievalResult, RetrievalRun, RetrievalScope
from app.services.retrieval import RetrievalService


class OwnerRetrievalRepository(Protocol):
    async def resolve_owner_scope(self, *, space_id: UUID, user_id: UUID) -> RetrievalScope | None: ...
    async def retrieve(self, *, scope: RetrievalScope, embedding: list[float], limit: int) -> list[RetrievedChunk]: ...
    async def get_current_chunks(self, *, scope: RetrievalScope, chunk_ids: tuple[UUID, ...]) -> list[RetrievedChunk]: ...
    async def add_run(self, run: RetrievalRun) -> None: ...
    async def get_run(self, run_id: UUID) -> RetrievalRun | None: ...


class OwnerRetrievalService:
    def __init__(self, *, repository: OwnerRetrievalRepository, retrieval: RetrievalService, model_name: str):
        self._repository, self._retrieval, self._model = repository, retrieval, model_name

    async def _scope(self, space_id: UUID, user_id: UUID) -> RetrievalScope:
        scope = await self._repository.resolve_owner_scope(space_id=space_id, user_id=user_id)
        if scope is None:
            raise RetrievalError('RETRIEVAL_NOT_FOUND', '空间或检索记录不存在。', 404)
        return scope

    async def search(self, *, space_id: UUID, user_id: UUID, question: str, top_k: int = 4) -> tuple[RetrievalRun, RetrievalResult]:
        scope = await self._scope(space_id, user_id)

        async def fetch(vector, limit):
            return await self._repository.retrieve(scope=scope, embedding=vector, limit=limit)

        result = await self._retrieval.search(question=question, fetch=fetch, top_k=top_k)
        current_scope = await self._scope(space_id, user_id)
        current = await self._repository.get_current_chunks(scope=current_scope, chunk_ids=tuple(x.id for x in result.items))
        if not scope.same_access(current_scope) or {x.id for x in current} != {x.id for x in result.items}:
            raise RetrievalError('RETRIEVAL_SCOPE_CHANGED', '资料范围已变化，请重新检索。', 409)
        run = RetrievalRun(uuid4(), scope, result.question, top_k, tuple(x.id for x in result.items),
                           tuple(x.score for x in result.items), result.timings_ms, self._model, datetime.now(UTC))
        await self._repository.add_run(run)
        return run, result

    async def get_run(self, run_id: UUID, *, user_id: UUID) -> tuple[RetrievalRun, tuple[RetrievedChunk, ...]]:
        run = await self._repository.get_run(run_id)
        if run is None or run.scope.user_id != user_id:
            raise RetrievalError('RETRIEVAL_NOT_FOUND', '空间或检索记录不存在。', 404)
        scope = await self._scope(run.scope.space_id, user_id)
        current = await self._repository.get_current_chunks(scope=scope, chunk_ids=run.chunk_ids)
        by_id = {x.id: x for x in current}
        return run, tuple(by_id[x] for x in run.chunk_ids if x in by_id)

    async def read_saved_evidence(self, *, space_id: UUID, user_id: UUID, chunk_ids: tuple[UUID, ...]):
        scope = await self._scope(space_id, user_id)
        chunks = await self._repository.get_current_chunks(scope=scope, chunk_ids=chunk_ids)
        latest = await self._scope(space_id, user_id)
        if not scope.same_access(latest):
            raise RetrievalError('RETRIEVAL_SCOPE_CHANGED', '资料范围已变化，请重新读取。', 409)
        current = await self._repository.get_current_chunks(scope=latest, chunk_ids=tuple(item.id for item in chunks))
        by_id = {item.id: item for item in current}
        return tuple(by_id[key] for key in chunk_ids if key in by_id), tuple(key for key in chunk_ids if key not in by_id)

    async def get_document_detail(self, *, space_id: UUID, document_id: UUID, user_id: UUID):
        scope = await self._scope(space_id, user_id)
        detail = await self._repository.get_document_detail(scope=scope, document_id=document_id)
        if detail is None:
            raise RetrievalError('DOCUMENT_NOT_FOUND', '资料不存在。', 404)
        current = await self._scope(space_id, user_id)
        if not scope.same_access(current):
            raise RetrievalError('RETRIEVAL_SCOPE_CHANGED', '资料范围已变化，请重新打开。', 409)
        chunks = await self._repository.get_current_chunks(scope=current, chunk_ids=tuple(item.id for item in detail['chunks']))
        if {item.id for item in chunks} != {item.id for item in detail['chunks']}:
            raise RetrievalError('RETRIEVAL_SCOPE_CHANGED', '资料范围已变化，请重新打开。', 409)
        return detail
