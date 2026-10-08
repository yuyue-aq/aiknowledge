from time import perf_counter
from app.domain.retrieval import RetrievalError,RetrievalResult
from app.services.hybrid_retrieval import branch_snapshot


class RerankedRetriever:
    """One authorized 50-item RRF pool, scored before the final selection."""
    def __init__(self,hybrid,reranker):
        self.hybrid,self.reranker=hybrid,reranker

    @property
    def config(self):
        return {**self.hybrid.config,'strategy':'hybrid_rerank','score_kind':'cross_encoder',
            'reranker':self.reranker.config,'pool_size':50}

    async def search(self,*,question,fetch,corpus,top_k,validate):
        started=perf_counter()
        if self.reranker is None:raise RetrievalError('RERANK_UNAVAILABLE','尚未配置本地重排模型。')
        result=await self.hybrid.search(question=question,fetch=fetch,corpus=corpus,top_k=50)
        authorized=tuple({item.id:item for items in [result.items,*result.branches.values()] for item in items}.values())
        await validate(authorized)
        scored=await self.reranker.rerank(question,result.items)
        if len(scored.items)!=len(result.items) or len({x.id for x in scored.items})!=len(scored.items) or {x.id for x in scored.items}!={x.id for x in result.items}:
            raise RetrievalError('RERANK_INVALID','重排模型返回的候选范围无效。')
        await validate(authorized)
        branches={**result.branches,'fusion':result.items}
        snapshot={**self.config,'branches':branch_snapshot(RetrievalResult(question,top_k,(),{},branches)),
            'rerank_inputs':list(scored.inputs),'rerank_timings_ms':scored.timings_ms}
        return RetrievalResult(question.strip(),top_k,scored.items[:top_k],{**result.timings_ms,
            'reranking':scored.timings_ms.get('inference',0.),'rerank_queue':scored.timings_ms.get('queue',0.),
            'total':round((perf_counter()-started)*1000,3)},branches,snapshot)
