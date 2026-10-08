import asyncio
import threading
from uuid import UUID

import pytest

from app.domain.conversations import RetrievedChunk
from app.domain.retrieval import RetrievalError
from app.infrastructure.reranking.bge import BgeReranker


def chunk(n):
    return RetrievedChunk(UUID(int=n),UUID(int=99),'private-filename.txt','正文'+str(n),None,n,.03,
        heading_path=('项目甲',),score_kind='rrf',fusion_rank=n,dense_rank=n)


class Tokenizer:
    def encode(self,text,**kwargs):return list(range(len(text)))
    def __call__(self,text,text_pair=None,**kwargs):return {'input_ids':[0,*self.encode(text),1,1,*self.encode(text_pair),2]}


class Model:
    tokenizer=Tokenizer()
    def __init__(self,scores):self.scores=scores;self.calls=[]
    def compute_score(self,pairs,**kwargs):
        self.calls.append((pairs,kwargs));return self.scores


@pytest.mark.asyncio
async def test_real_adapter_is_lazy_preserves_scores_provenance_and_hides_filename():
    model=Model([-3.,2.]);created=[]
    def factory(**kwargs):created.append(kwargs);return model
    adapter=BgeReranker(model_name='local',revision='pinned',model_factory=factory)
    assert not created
    result=await adapter.rerank('查项目甲',[chunk(1),chunk(2)])
    assert [x.id.int for x in result.items]==[2,1]
    assert result.items[0].score==2. and result.items[0].score_kind=='cross_encoder'
    assert result.items[0].fusion_rank==2 and result.items[0].fusion_score==.03
    assert result.items[0].rerank_rank==1
    assert 'private-filename' not in str(model.calls)
    assert model.calls[0][1]['normalize'] is False
    assert result.config['revision']=='pinned'
    assert result.inputs[0]['truncated'] is False and result.inputs[0]['pair_tokens']>0


@pytest.mark.asyncio
async def test_empty_pool_never_initializes_and_duplicates_score_once_with_stable_ties():
    model=Model([1.,1.]);calls=[]
    def factory(**kwargs):calls.append(kwargs);return model
    adapter=BgeReranker(model_name='local',revision='pinned',model_factory=factory)
    assert not (await adapter.rerank('问题',[])).items and not calls
    result=await adapter.rerank('问题',[chunk(2),chunk(2),chunk(1)])
    assert [x.id.int for x in result.items]==[1,2]
    assert len(model.calls[0][0])==2


@pytest.mark.asyncio
@pytest.mark.parametrize('scores',[[1.],[float('nan'),1.],[True,1.],['1',2.],[float('inf'),1.]])
async def test_invalid_scores_fail_closed(scores):
    adapter=BgeReranker(model_name='local',revision='pinned',model_factory=lambda **kwargs:Model(scores))
    with pytest.raises(RetrievalError) as error:await adapter.rerank('问题',[chunk(1),chunk(2)])
    assert error.value.code=='RERANK_INVALID'


@pytest.mark.asyncio
async def test_long_input_does_not_silently_truncate_or_compute():
    model=Model([1.]);adapter=BgeReranker(model_name='local',revision='pinned',max_length=16,
        query_max_length=8,model_factory=lambda **kwargs:model)
    with pytest.raises(RetrievalError) as error:await adapter.rerank('这是超过查询输入限制的问题',[chunk(1)])
    assert error.value.code=='RERANK_INPUT_LIMIT' and not model.calls


@pytest.mark.asyncio
async def test_timeout_does_not_allow_concurrent_second_thread_or_reload():
    started=threading.Event();release=threading.Event();loaded=[]
    class Blocking(Model):
        def compute_score(self,pairs,**kwargs):
            started.set();release.wait(2);return [1.]
    def factory(**kwargs):loaded.append(1);return Blocking([1.])
    adapter=BgeReranker(model_name='local',revision='pinned',timeout_seconds=.02,model_factory=factory)
    try:
        with pytest.raises(RetrievalError) as first:await adapter.rerank('问题',[chunk(1)])
        assert started.is_set() and first.value.code=='RERANK_TIMEOUT'
        with pytest.raises(RetrievalError) as second:await adapter.rerank('问题',[chunk(1)])
        assert second.value.code=='RERANK_BUSY' and loaded==[1]
    finally:release.set()
    await asyncio.sleep(.05)
    assert (await adapter.rerank('问题',[chunk(1)])).items and loaded==[1]


@pytest.mark.asyncio
async def test_model_failure_does_not_expose_provider_details():
    def factory(**kwargs):raise RuntimeError('private filesystem/provider detail')
    adapter=BgeReranker(model_name='local',revision='pinned',model_factory=factory)
    with pytest.raises(RetrievalError) as error:await adapter.rerank('问题',[chunk(1)])
    assert error.value.code=='RERANK_UNAVAILABLE' and 'private' not in str(error.value)


@pytest.mark.asyncio
async def test_cancelled_request_retains_thread_and_model_until_completion():
    started=threading.Event();release=threading.Event();loaded=[]
    class Blocking(Model):
        def compute_score(self,pairs,**kwargs):
            started.set();release.wait(2);return [1.]
    def factory(**kwargs):loaded.append(1);return Blocking([1.])
    adapter=BgeReranker(model_name='local',model_factory=factory)
    request=asyncio.create_task(adapter.rerank('问题',[chunk(1)]))
    try:
        for _ in range(100):
            if started.is_set():break
            await asyncio.sleep(.005)
        assert started.is_set()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):await request
        with pytest.raises(RetrievalError) as error:await adapter.rerank('问题',[chunk(1)])
        assert error.value.code=='RERANK_BUSY' and loaded==[1]
    finally:release.set()
    await adapter._active
    assert (await adapter.rerank('问题',[chunk(1)])).items and loaded==[1]


@pytest.mark.asyncio
async def test_pair_length_limit_rejects_long_passage_without_scoring():
    model=Model([1.]);adapter=BgeReranker(model_name='local',max_length=16,
        query_max_length=8,model_factory=lambda **kwargs:model)
    with pytest.raises(RetrievalError) as error:await adapter.rerank('问',[chunk(1)])
    assert error.value.code=='RERANK_INPUT_LIMIT' and not model.calls


@pytest.mark.asyncio
async def test_candidate_overflow_never_loads_model():
    loaded=[]
    def factory(**kwargs):loaded.append(1);return Model([])
    adapter=BgeReranker(model_name='local',model_factory=factory)
    with pytest.raises(RetrievalError) as error:await adapter.rerank('问',[chunk(n) for n in range(1,52)])
    assert error.value.code=='RERANK_CANDIDATE_LIMIT' and not loaded
