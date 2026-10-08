"""Pinned local cross encoder. No remote code; no silent token truncation."""
import asyncio
import hashlib
import json
import math
from dataclasses import dataclass,replace
from pathlib import Path
from time import perf_counter

from app.domain.retrieval import RetrievalError

MODEL_ID='BAAI/bge-reranker-v2-m3'
REVISION='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'


@dataclass(frozen=True)
class RerankResult:
    items: tuple
    config: dict
    inputs: tuple
    timings_ms: dict


class BgeReranker:
    def __init__(self,*,model_name,revision=REVISION,batch_size=4,max_length=1024,
                 query_max_length=512,timeout_seconds=600.,model_factory=None):
        if not 1<=batch_size<=16 or not 8<=max_length<=2048 or not 1<=query_max_length<max_length or timeout_seconds<=0:
            raise ValueError('Invalid reranker limits')
        self.model_name,self.revision=model_name,revision
        self.batch_size,self.max_length,self.query_max_length=batch_size,max_length,query_max_length
        self.timeout=timeout_seconds;self._factory=model_factory or self._default_factory
        self._model=None;self._lock=asyncio.Lock();self._active=None

    @property
    def config(self):
        return {'model':MODEL_ID,'revision':self.revision,'score_kind':'cross_encoder','normalize':False,
            'device':'cpu','use_fp16':False,'batch_size':self.batch_size,'max_length':self.max_length,
            'query_max_length':self.query_max_length,'candidate_limit':50,'input_version':'heading-body-v1',
            'truncation':'reject','timeout_seconds':self.timeout}

    async def rerank(self,question,candidates):
        if not isinstance(question,str) or not question.strip():
            raise RetrievalError('RERANK_INPUT_LIMIT','重排问题不能为空。',422)
        unique={}
        for item in candidates:unique.setdefault(item.id,item)
        items=tuple(unique.values())
        if len(items)>50:raise RetrievalError('RERANK_CANDIDATE_LIMIT','重排候选不能超过50个。',422)
        if not items:return RerankResult((),self.config,(),{'queue':0.,'inference':0.,'model_load':0.})
        queued=perf_counter()
        try:await asyncio.wait_for(self._lock.acquire(),timeout=self.timeout)
        except TimeoutError as exc:raise RetrievalError('RERANK_TIMEOUT','重排模型排队超时，请稍后重试。') from exc
        try:
            if self._active is not None and not self._active.done():
                raise RetrievalError('RERANK_BUSY','重排模型仍在处理，请稍后重试。')
            wait_ms=(perf_counter()-queued)*1000
            self._active=asyncio.create_task(asyncio.to_thread(self._score,question.strip(),items,wait_ms))
            self._active.add_done_callback(lambda task:task.exception() if not task.cancelled() else None)
            try:return await asyncio.wait_for(asyncio.shield(self._active),timeout=self.timeout)
            except TimeoutError as exc:raise RetrievalError('RERANK_TIMEOUT','重排模型处理超时，请稍后重试。') from exc
        finally:self._lock.release()

    def _score(self,question,items,wait_ms):
        started=perf_counter();load_ms=0.
        try:
            if self._model is None:
                self._model=self._factory(model_name=self.model_name,revision=self.revision,batch_size=self.batch_size,
                    max_length=self.max_length,query_max_length=self.query_max_length)
                load_ms=(perf_counter()-started)*1000
            tokenizer=self._model.tokenizer
            query=tokenizer.encode(question,add_special_tokens=False)
            if len(query)>self.query_max_length:
                raise RetrievalError('RERANK_INPUT_LIMIT','问题超过重排模型输入上限，请缩短问题。',422)
            pairs=[];inputs=[]
            for item in items:
                passage='章节：'+(' / '.join(item.heading_path) or '未提供')+'\n正文：'+item.content
                tokens=tokenizer.encode(passage,add_special_tokens=False)
                length=len(tokenizer(question,text_pair=passage,truncation=False,add_special_tokens=True)['input_ids'])
                if length>self.max_length:
                    raise RetrievalError('RERANK_INPUT_LIMIT','片段与问题超过重排输入上限，请调整分块或缩短问题。',422)
                pairs.append([question,passage])
                inputs.append({'chunk_id':str(item.id),'query_tokens':len(query),'passage_tokens':len(tokens),
                    'pair_tokens':length,'truncated':False,'input_hash':hashlib.sha256((question+'\0'+passage).encode()).hexdigest()})
            raw=self._model.compute_score(pairs,batch_size=self.batch_size,max_length=self.max_length,
                query_max_length=self.query_max_length,normalize=False)
            if hasattr(raw,'tolist'):raw=raw.tolist()
            if not isinstance(raw,(list,tuple)):raw=[raw]
            if len(raw)!=len(items):raise ValueError('Score count mismatch')
            scores=[]
            for value in raw:
                if isinstance(value,(str,bool)):raise ValueError('Non-numeric score')
                score=float(value)
                if not math.isfinite(score):raise ValueError('Non-finite score')
                scores.append(score)
            ranked=sorted((replace(item,score=score,score_kind='cross_encoder',rerank_score=score,
                fusion_score=item.score) for item,score in zip(items,scores)),key=lambda item:(-item.score,str(item.id)))
            ranked=tuple(replace(item,rerank_rank=rank) for rank,item in enumerate(ranked,1))
            return RerankResult(ranked,self.config,tuple(inputs),{'queue':round(wait_ms,3),
                'inference':round((perf_counter()-started)*1000,3),'model_load':round(load_ms,3)})
        except RetrievalError:raise
        except (ValueError,TypeError,OverflowError) as exc:
            raise RetrievalError('RERANK_INVALID','重排模型返回数据无效。') from exc
        except Exception as exc:
            raise RetrievalError('RERANK_UNAVAILABLE','本地重排模型暂时不可用，请稍后重试。') from exc

    @staticmethod
    def _default_factory(*,model_name,revision,**kwargs):
        folder=Path(model_name)
        manifest=json.loads((folder/'pinned-manifest.json').read_text(encoding='utf-8'))
        if manifest['repo_id']!=MODEL_ID or manifest['revision']!=revision:
            raise RuntimeError('Model revision does not match configured snapshot')
        expected=next(item for item in manifest['files'] if item['rfilename']=='model.safetensors')['lfs']['sha256']
        digest=hashlib.sha256()
        with (folder/'model.safetensors').open('rb') as stream:
            while block:=stream.read(4*1024*1024):digest.update(block)
        if digest.hexdigest()!=expected:raise RuntimeError('Model weight checksum mismatch')
        from FlagEmbedding import FlagReranker
        return FlagReranker(str(folder),devices='cpu',use_fp16=False,trust_remote_code=False,
            batch_size=kwargs['batch_size'],max_length=kwargs['max_length'],query_max_length=kwargs['query_max_length'],normalize=False)
