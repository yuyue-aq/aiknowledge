import asyncio
from dataclasses import asdict
from datetime import UTC,datetime
from hashlib import sha256
import json
from app.domain.documents import is_document_available
from app.domain.retrieval import RetrievalError
from app.services.chunk_plan import plan_chunks
from app.services.document_parsing import DocumentParseError


class DocumentChunkingService:
    def __init__(self,*,owner_retrieval,document_repository,storage,embedding_client,uploader,parser,model_name):
        self.owner,self.repository,self.storage=owner_retrieval,document_repository,storage
        self.embedding_client,self.uploader,self.parser,self.model_name=embedding_client,uploader,parser,model_name

    async def _detail(self,space_id,document_id,user_id):
        detail=await self.owner.get_document_detail(space_id=space_id,document_id=document_id,user_id=user_id)
        if detail['document'].active_version_id is None or not is_document_available(detail['document'],now=datetime.now(UTC)):
            raise RetrievalError('CHUNK_SOURCE_UNAVAILABLE','资料当前不可用，不能预览或重建。',409)
        return detail

    def _fingerprint(self,doc,config):
        payload={'document':str(doc.id),'version':str(doc.active_version_id),'source':doc.sha256,
            'model':self.model_name,'config':config.snapshot()}
        return sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()

    async def _source(self,doc):
        await self.repository.commit()
        try:source=await self.storage.get_bytes(doc.storage_key)
        except Exception as exc:raise RetrievalError('CHUNK_SOURCE_READ_FAILED','原文件暂时不可读取，请稍后重试。') from exc
        if sha256(source).hexdigest()!=doc.sha256:
            raise RetrievalError('CHUNK_SOURCE_CHANGED','原文件校验不一致，请重新确认资料。',409)
        return source

    async def preview(self,*,space_id,document_id,user_id,config,offset=0,limit=12):
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=50:
            raise RetrievalError('CHUNK_PAGE_INVALID','预览分页参数无效。',422)
        detail=await self._detail(space_id,document_id,user_id);doc=detail['document']
        fingerprint=self._fingerprint(doc,config);source=await self._source(doc)
        try:
            parsed=await asyncio.to_thread(self.parser.parse,filename=doc.original_filename,content=source)
            budget=await self.embedding_client.document_token_budget()
            candidate=await asyncio.to_thread(plan_chunks,parsed,budget,config)
        except DocumentParseError as exc:
            raise RetrievalError('CHUNK_PREVIEW_INVALID',str(exc),422) from exc
        except ValueError as exc:
            raise RetrievalError('CHUNK_PREVIEW_INVALID','分块预览失败，请检查配置或资料长度。',422) from exc
        except RuntimeError as exc:
            raise RetrievalError('CHUNK_PREVIEW_UNAVAILABLE','本地模型暂时不可用，请稍后重新预览。') from exc
        latest=await self._detail(space_id,document_id,user_id)
        if self._fingerprint(latest['document'],config)!=fingerprint:
            raise RetrievalError('CHUNK_SOURCE_CHANGED','资料版本已变化，请重新预览。',409)
        current=detail['chunks'];fields=('ordinal','content','heading_path','page_number','source_block_id','char_start','char_end','content_hash','token_count')
        current_config=next((dict(v.chunk_config) for v in detail['versions'] if v.id==doc.active_version_id),{})
        return {'document_id':doc.id,'document_version_id':doc.active_version_id,'source_sha256':doc.sha256,
            'fingerprint':fingerprint,'embedding_model':self.model_name,'current_config':current_config,
            'candidate_config':config.snapshot(),'current_total':len(current),'candidate_total':len(candidate),
            'offset':offset,'limit':limit,'current':[{key:getattr(x,key,None) for key in fields} for x in current[offset:offset+limit]],
            'candidate':[asdict(x) for x in candidate[offset:offset+limit]]}

    async def rebuild(self,*,space_id,document_id,user_id,config,expected_version_id,fingerprint):
        detail=await self._detail(space_id,document_id,user_id);doc=detail['document']
        if doc.active_version_id!=expected_version_id or self._fingerprint(doc,config)!=fingerprint:
            raise RetrievalError('CHUNK_SOURCE_CHANGED','预览或配置已变化，请重新预览后再重建。',409)
        current_config=next((dict(v.chunk_config) for v in detail['versions'] if v.id==doc.active_version_id),{})
        if current_config==config.snapshot():raise RetrievalError('CHUNK_ALREADY_APPLIED','当前版本已使用相同分块配置。',409)
        source=await self._source(doc)
        latest=await self._detail(space_id,document_id,user_id)
        if self._fingerprint(latest['document'],config)!=fingerprint:
            raise RetrievalError('CHUNK_SOURCE_CHANGED','资料版本已变化，请重新预览。',409)
        return await self.uploader.upload(space_id=space_id,category_id=doc.category_id,filename=doc.original_filename,
            content=source,content_type=doc.mime_type,owner_user_id=user_id,is_enabled=doc.is_enabled,
            effective_at=doc.effective_at,expires_at=doc.expires_at,_replacing_document=doc,_chunk_config=config.snapshot())
