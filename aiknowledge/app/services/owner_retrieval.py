from datetime import UTC, datetime
import asyncio
from time import perf_counter
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.conversations import RetrievedChunk
from app.domain.retrieval import RetrievalError, RetrievalResult, RetrievalRun, RetrievalScope
from app.services.retrieval import RetrievalService
from app.services.bm25 import Bm25Retriever


class OwnerRetrievalRepository(Protocol):
    async def resolve_owner_scope(self, *, space_id: UUID, user_id: UUID) -> RetrievalScope | None: ...
    async def retrieve(self, *, scope: RetrievalScope, embedding: list[float], limit: int) -> list[RetrievedChunk]: ...
    async def get_current_chunks(self, *, scope: RetrievalScope, chunk_ids: tuple[UUID, ...]) -> list[RetrievedChunk]: ...
    async def add_run(self, run: RetrievalRun) -> None: ...
    async def get_run(self, run_id: UUID) -> RetrievalRun | None: ...
    async def keyword_corpus(self, *, scope: RetrievalScope, limit: int) -> list[RetrievedChunk]: ...


class OwnerRetrievalService:
    def __init__(self, *, repository: OwnerRetrievalRepository, retrieval: RetrievalService, model_name: str, bm25: Bm25Retriever | None = None):
        self._repository, self._retrieval, self._model = repository, retrieval, model_name
        self._bm25=bm25 or Bm25Retriever()

    async def _scope(self, space_id: UUID, user_id: UUID) -> RetrievalScope:
        scope = await self._repository.resolve_owner_scope(space_id=space_id, user_id=user_id)
        if scope is None:
            raise RetrievalError('RETRIEVAL_NOT_FOUND', '空间或检索记录不存在。', 404)
        return scope

    async def search(self, *, space_id: UUID, user_id: UUID, question: str, top_k: int = 4, strategy: str = 'dense') -> tuple[RetrievalRun, RetrievalResult]:
        if strategy not in ('dense','bm25'):raise RetrievalError('RETRIEVAL_INPUT_INVALID','不支持的检索方式。',422)
        if not isinstance(question,str) or not question.strip() or len(question.strip())>2000:
            raise RetrievalError('RETRIEVAL_INPUT_INVALID','请输入1—2000字的问题。',422)
        if isinstance(top_k,bool) or not isinstance(top_k,int) or not 1<=top_k<=20:
            raise RetrievalError('RETRIEVAL_INPUT_INVALID','Top K必须为1—20的整数。',422)
        scope = await self._scope(space_id, user_id)

        async def fetch(vector, limit):
            return await self._repository.retrieve(scope=scope, embedding=vector, limit=limit)

        if strategy=='bm25':
            started=perf_counter()
            try:corpus=await self._repository.keyword_corpus(scope=scope,limit=self._bm25.max_corpus_chunks+1)
            except Exception as exc:raise RetrievalError('RETRIEVAL_UNAVAILABLE','关键词检索暂时不可用，请稍后重试。') from exc
            fetched=perf_counter()
            items=await asyncio.to_thread(self._bm25.rank,question,corpus,top_k)
            ranked=perf_counter()
            result=RetrievalResult(question.strip(),top_k,items,{'embedding':0.,'corpus':round((fetched-started)*1000,3),
                'ranking':round((ranked-fetched)*1000,3),'total':round((ranked-started)*1000,3)})
        else:result = await self._retrieval.search(question=question, fetch=fetch, top_k=top_k)
        current_scope = await self._scope(space_id, user_id)
        current = await self._repository.get_current_chunks(scope=current_scope, chunk_ids=tuple(x.id for x in result.items))
        if not scope.same_access(current_scope) or {x.id for x in current} != {x.id for x in result.items}:
            raise RetrievalError('RETRIEVAL_SCOPE_CHANGED', '资料范围已变化，请重新检索。', 409)
        run = RetrievalRun(uuid4(), scope, result.question, top_k, tuple(x.id for x in result.items),
                           tuple(x.score for x in result.items), result.timings_ms,
                           'bm25-zh-bigram-v1' if strategy=='bm25' else self._model, datetime.now(UTC),strategy,
                           self._bm25.config if strategy=='bm25' else {'score_kind':'cosine'})
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
