"""Scope-local Dense + independent BM25 with reciprocal rank fusion.

Ranks are 1-based; scores from different branches are never added directly.
Database callbacks run sequentially: an AsyncSession is not concurrently safe.
"""
import asyncio
from dataclasses import replace
from time import perf_counter

from app.domain.retrieval import RetrievalError, RetrievalResult
from app.services.bm25 import Bm25Retriever


def reciprocal_rank_fusion(dense, keyword, *, top_k, rank_constant=60):
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError('top_k must be a positive integer')
    if isinstance(rank_constant, bool) or not isinstance(rank_constant, int) or rank_constant < 1:
        raise ValueError('rank_constant must be a positive integer')
    branches=[]
    for items in (dense,keyword):
        unique={}
        for item in items:unique.setdefault(item.id,item)
        branches.append({item.id:(rank,item) for rank,item in enumerate(unique.values(),1)})
    d,b=branches
    scored=[]
    for key in d.keys() | b.keys():
        dr,di=d.get(key,(None,None));br,bi=b.get(key,(None,None))
        score=(1/(rank_constant+dr) if dr else 0)+(1/(rank_constant+br) if br else 0)
        scored.append(replace(di or bi,score=score,score_kind='rrf',dense_rank=dr,bm25_rank=br,
            dense_score=di.score if di else None,bm25_score=bi.score if bi else None))
    ordered=sorted(scored,key=lambda item:(-item.score,str(item.id)))[:top_k]
    return tuple(replace(item,fusion_rank=rank) for rank,item in enumerate(ordered,1))


class HybridRetriever:
    rank_constant=60
    rank_window_size=50

    def __init__(self,dense,bm25=None):
        self.dense=dense
        self.bm25=bm25 or Bm25Retriever()

    @property
    def config(self):
        return {'strategy':'hybrid','score_kind':'rrf','rank_constant':self.rank_constant,
            'rank_window_size':self.rank_window_size,'bm25':self.bm25.config,'branch_failure':'fail_closed'}

    async def search(self,*,question,fetch,corpus,top_k):
        start=perf_counter()
        dense=await self.dense.search(question=question,fetch=fetch,top_k=self.rank_window_size)
        try:
            chunks=await corpus(self.bm25.max_corpus_chunks+1)
        except RetrievalError:raise
        except Exception as exc:
            raise RetrievalError('RETRIEVAL_UNAVAILABLE','混合检索暂时不可用，请稍后重试。') from exc
        fetched=perf_counter()
        keyword=await asyncio.to_thread(self.bm25.rank,question,chunks,self.rank_window_size,maximum_k=self.rank_window_size)
        ranked=perf_counter()
        items=reciprocal_rank_fusion(dense.items,keyword,top_k=top_k,rank_constant=self.rank_constant)
        end=perf_counter()
        return RetrievalResult(question.strip(),top_k,items,{**dense.timings_ms,
            'corpus':round((fetched-start)*1000-dense.timings_ms['total'],3),
            'bm25_ranking':round((ranked-fetched)*1000,3),'fusion':round((end-ranked)*1000,3),
            'total':round((end-start)*1000,3)}, {'dense':dense.items,'bm25':keyword})


def branch_snapshot(result):
    return {name:[{'chunk_id':str(item.id),'rank':rank,'score':item.score}
        for rank,item in enumerate(items,1)] for name,items in result.branches.items()}
