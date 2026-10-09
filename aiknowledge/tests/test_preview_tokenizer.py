import asyncio,time
import pytest
from app.infrastructure.embeddings.bge import BgeEmbeddingClient
from app.services.token_budget import TokenBudget

@pytest.mark.asyncio
async def test_preview_initializes_tokenizer_once_without_loading_or_encoding_weights():
    calls=[]
    def tokens(**kw):calls.append(kw);return TokenBudget(lambda x,**kw:{'input_ids':[0]*(len(x)+2)},capacity=512)
    def weights(**kw):raise AssertionError('Preview must not load model weights')
    client=BgeEmbeddingClient(model_name='local',expected_dimension=1024,model_factory=weights,token_budget_factory=tokens)
    a,b=await asyncio.gather(client.document_token_budget(),client.document_token_budget())
    assert a is b and a.count('原文')==4 and len(calls)==1 and client._model is None

@pytest.mark.asyncio
async def test_cancelled_tokenizer_initialization_is_retained_for_next_request():
    calls=[]
    def tokens(**kw):
        calls.append(1);time.sleep(.05);return TokenBudget(lambda x,**kw:{'input_ids':[0]*(len(x)+2)})
    client=BgeEmbeddingClient(model_name='local',expected_dimension=1024,token_budget_factory=tokens)
    task=asyncio.create_task(client.document_token_budget());await asyncio.sleep(.01);task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert (await client.document_token_budget()).count('文')==3 and calls==[1]
