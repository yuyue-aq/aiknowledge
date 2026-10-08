from dataclasses import replace
from uuid import UUID
import pytest

from app.domain.conversations import RetrievedChunk
from app.domain.retrieval import RetrievalError,RetrievalResult
from app.infrastructure.reranking.bge import RerankResult
from app.services.reranked_retrieval import RerankedRetriever


def chunks():
    return tuple(RetrievedChunk(UUID(int=i),UUID(int=99),'来源','正文'+str(i),None,i,.03-i*.0001,
        score_kind='rrf',fusion_rank=i) for i in range(1,16))


class Hybrid:
    config={'rank_window_size':50,'score_kind':'rrf'}
    async def search(self,**kwargs):
        assert kwargs['top_k']==50
        return RetrievalResult(kwargs['question'],50,chunks(),{'embedding':1.,'total':2.},{'dense':chunks(),'bm25':()})


class Reranker:
    config={'model':'real-port-fixture','revision':'pinned'}
    calls=[]
    async def rerank(self,q,items):
        self.calls.append(tuple(x.id for x in items))
        ranked=tuple(replace(x,score=1.,score_kind='cross_encoder',rerank_rank=n,fusion_score=x.score)
            for n,x in enumerate(reversed(items),1))
        return RerankResult(ranked,self.config,(),{'inference':4.})


@pytest.mark.asyncio
async def test_reranking_occurs_before_final_cut_and_preserves_same_before_pool():
    scorer=Reranker();scorer.calls=[];checks=[]
    async def validate(items):checks.append(tuple(x.id for x in items))
    result=await RerankedRetriever(Hybrid(),scorer).search(question='问题',fetch=None,corpus=None,top_k=3,validate=validate)
    assert len(scorer.calls[0])==15 and result.items[0].id.int==15
    assert result.branches['fusion'][0].id.int==1 and len(result.branches['fusion'])==15
    assert len(checks)==2 and set(checks[0])==set(checks[1])
    assert result.config_snapshot['reranker']['revision']=='pinned'
    assert result.timings_ms['reranking']==4.


@pytest.mark.asyncio
async def test_access_revocation_before_model_never_calls_reranker():
    scorer=Reranker();scorer.calls=[]
    async def deny(items):raise RetrievalError('RETRIEVAL_SCOPE_CHANGED','范围变化',409)
    with pytest.raises(RetrievalError):
        await RerankedRetriever(Hybrid(),scorer).search(question='问题',fetch=None,corpus=None,top_k=3,validate=deny)
    assert not scorer.calls


@pytest.mark.asyncio
async def test_unknown_or_removed_ids_from_reranker_are_rejected():
    class Invalid(Reranker):
        async def rerank(self,q,items):
            return RerankResult((replace(items[0],id=UUID(int=500)),),self.config,(),{})
    async def validate(items):pass
    with pytest.raises(RetrievalError) as error:
        await RerankedRetriever(Hybrid(),Invalid()).search(question='问题',fetch=None,corpus=None,top_k=3,validate=validate)
    assert error.value.code=='RERANK_INVALID'


@pytest.mark.asyncio
async def test_revocation_during_model_execution_never_returns_old_results():
    scorer=Reranker();scorer.calls=[];checks=[]
    async def validate(items):
        checks.append(1)
        if len(checks)==2:raise RetrievalError('RETRIEVAL_SCOPE_CHANGED','范围变化',409)
    with pytest.raises(RetrievalError) as error:
        await RerankedRetriever(Hybrid(),scorer).search(question='问题',fetch=None,corpus=None,top_k=3,validate=validate)
    assert error.value.code=='RETRIEVAL_SCOPE_CHANGED' and len(scorer.calls)==1 and len(checks)==2
