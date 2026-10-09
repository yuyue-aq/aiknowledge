from dataclasses import replace
from datetime import UTC,datetime
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID
import pytest
from app.domain.documents import StoredDocument,DocumentStatus,DocumentBlock,DocumentFormat,ParsedDocument
from app.domain.retrieval import RetrievalError
from app.services.chunk_plan import ChunkConfig
from app.services.document_chunking import DocumentChunkingService
from app.services.token_budget import TokenBudget

SID=UUID(int=1);DID=UUID(int=2);VID=UUID(int=3);USER=UUID(int=4)
SOURCE='第一段事实。\n\n第二段事实。'.encode()
NOW=datetime.now(UTC)
def doc():return StoredDocument(DID,SID,None,'验证.txt','private-key','text/plain',len(SOURCE),sha256(SOURCE).hexdigest(),DocumentStatus.READY,VID,NOW,NOW)

class Owner:
    def __init__(self):self.document=doc();self.deny=False;self.calls=0
    async def get_document_detail(self,**kw):
        self.calls+=1
        if self.deny:raise RetrievalError('RETRIEVAL_NOT_FOUND','不存在',404)
        return {'document':self.document,'versions':[SimpleNamespace(id=VID,chunk_config={'strategy_version':'sentence-token-budget-v2'})],
            'chunks':[SimpleNamespace(ordinal=1,content='现有片段',heading_path=(),page_number=None,source_block_id='block-1',char_start=0,char_end=4,content_hash='hash',token_count=6)]}

class Repository:
    async def commit(self):pass
class Storage:
    calls=0
    async def get_bytes(self,key):self.calls+=1;return SOURCE
class Encoder:
    async def document_token_budget(self):return TokenBudget(lambda text,**kw:{'input_ids':list(range(len(text)+2))},capacity=64)
    async def embed_documents(self,texts):raise AssertionError('Preview must not encode vectors')
class Parser:
    def parse(self,**kw):return ParsedDocument('验证.txt',DocumentFormat.TEXT,(DocumentBlock(SOURCE.decode(),(),1),))
class Uploader:
    calls=[]
    async def upload(self,**kw):self.calls.append(kw);return SimpleNamespace(version=SimpleNamespace(id=UUID(int=5)))

def service(owner=None):
    owner=owner or Owner();storage=Storage();uploader=Uploader();uploader.calls=[]
    return DocumentChunkingService(owner_retrieval=owner,document_repository=Repository(),storage=storage,
        embedding_client=Encoder(),uploader=uploader,parser=Parser(),model_name='model'),owner,storage,uploader

@pytest.mark.asyncio
async def test_preview_uses_actual_baseline_and_same_candidate_spans_no_embeddings():
    svc,owner,storage,upload=service();cfg=ChunkConfig(max_tokens=64,overlap_characters=0)
    result=await svc.preview(space_id=SID,document_id=DID,user_id=USER,config=cfg,offset=0,limit=1)
    assert result['current'][0]['content']=='现有片段'
    assert result['candidate_total']==2 and len(result['candidate'])==1
    assert result['candidate_config']==cfg.snapshot() and not upload.calls
    assert owner.calls==2 and storage.calls==1

@pytest.mark.asyncio
async def test_permission_denied_before_source_or_tokenizer_access():
    owner=Owner();owner.deny=True;svc,_,storage,_=service(owner)
    with pytest.raises(RetrievalError):await svc.preview(space_id=SID,document_id=DID,user_id=USER,config=ChunkConfig(max_tokens=64))
    assert storage.calls==0

@pytest.mark.asyncio
async def test_source_disabled_during_preview_does_not_return_cached_content():
    owner=Owner()
    class Changing(Encoder):
        async def document_token_budget(self):
            owner.document=replace(owner.document,is_enabled=False)
            return await super().document_token_budget()
    svc,_,_,_=service(owner);svc.embedding_client=Changing()
    with pytest.raises(RetrievalError) as error:await svc.preview(space_id=SID,document_id=DID,user_id=USER,config=ChunkConfig(max_tokens=64))
    assert error.value.status_code==409

@pytest.mark.asyncio
async def test_rebuild_binds_fingerprint_to_current_version_and_explicit_config():
    svc,owner,_,upload=service();cfg=ChunkConfig(max_tokens=64,overlap_characters=0)
    preview=await svc.preview(space_id=SID,document_id=DID,user_id=USER,config=cfg)
    await svc.rebuild(space_id=SID,document_id=DID,user_id=USER,config=cfg,expected_version_id=VID,fingerprint=preview['fingerprint'])
    assert upload.calls[0]['_replacing_document'].id==DID and upload.calls[0]['_chunk_config']==cfg.snapshot()
    assert upload.calls[0]['content']==SOURCE
    owner.document=replace(owner.document,active_version_id=UUID(int=99))
    with pytest.raises(RetrievalError) as error:await svc.rebuild(space_id=SID,document_id=DID,user_id=USER,config=cfg,expected_version_id=VID,fingerprint=preview['fingerprint'])
    assert error.value.status_code==409 and len(upload.calls)==1

@pytest.mark.asyncio
async def test_changed_config_requires_new_preview_and_invalid_page_rejected():
    svc,_,storage,upload=service();cfg=ChunkConfig(max_tokens=64)
    preview=await svc.preview(space_id=SID,document_id=DID,user_id=USER,config=cfg)
    with pytest.raises(RetrievalError):await svc.rebuild(space_id=SID,document_id=DID,user_id=USER,config=ChunkConfig(max_tokens=32),expected_version_id=VID,fingerprint=preview['fingerprint'])
    assert not upload.calls
    with pytest.raises(RetrievalError):await svc.preview(space_id=SID,document_id=DID,user_id=USER,config=cfg,offset=-1,limit=51)
