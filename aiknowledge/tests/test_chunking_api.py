from types import SimpleNamespace
from uuid import UUID
import httpx
import pytest
from app.main import create_app
from app.core.config import Settings
from app.api.dependencies import get_current_user,get_database_session
from app.domain.retrieval import RetrievalError
from app.domain.documents import DocumentSubmission,StoredDocumentVersion,DocumentVersionStatus
from app.services.chunk_plan import ChunkConfig
from test_document_chunking import SID,DID,VID,USER,doc,NOW

class Service:
    calls=[];error=None
    async def preview(self,**kw):
        self.calls.append(kw)
        if self.error:raise self.error
        return {'document_id':DID,'document_version_id':VID,'source_sha256':'a'*64,'fingerprint':'b'*64,
            'embedding_model':'model','current_config':{},'candidate_config':kw['config'].snapshot(),
            'current_total':1,'candidate_total':1,'offset':kw['offset'],'limit':kw['limit'],
            'current':[],'candidate':[{'ordinal':1,'content':'原文','heading_path':['章节'],'page_number':1,'source_block_id':'block-1','char_start':0,'char_end':2,'content_hash':'c'*64,'token_count':4}]}
    async def rebuild(self,**kw):
        self.calls.append(kw)
        version=StoredDocumentVersion(UUID(int=5),DID,2,'parser','local','model',1024,kw['config'].snapshot(),DocumentVersionStatus.PROCESSING,NOW)
        return DocumentSubmission(doc(),version,True)

def app(service,logged=True):
    result=create_app(settings=Settings(_env_file=None,auth_required=True))
    async def session():yield object()
    result.dependency_overrides[get_database_session]=session
    if logged:result.dependency_overrides[get_current_user]=lambda:SimpleNamespace(id=USER)
    result.state.chunking_service_factory=lambda s:service
    return result

@pytest.mark.asyncio
async def test_preview_and_rebuild_owner_api_use_validated_config_and_actual_data():
    s=Service();s.calls=[]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(s)),base_url='http://test') as c:
        route=f'/api/v1/owner/spaces/{SID}/documents/{DID}'
        r=await c.post(route+'/chunk-preview',json={'strategy':'structure','max_tokens':128,'overlap_characters':0})
        assert r.status_code==200 and r.json()['candidate'][0]['char_end']==2
        assert s.calls[0]['user_id']==USER and s.calls[0]['config'].max_tokens==128
        r=await c.post(route+'/rechunk',json={'strategy':'structure','max_tokens':128,'overlap_characters':0,'expected_version_id':str(VID),'fingerprint':'b'*64})
        assert r.status_code==202 and r.json()['version_id']==str(UUID(int=5))

@pytest.mark.asyncio
async def test_invalid_config_extra_fields_and_anonymous_are_rejected_before_service():
    s=Service();s.calls=[];route=f'/api/v1/owner/spaces/{SID}/documents/{DID}/chunk-preview'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(s)),base_url='http://test') as c:
        for payload in [{'max_tokens':True},{'max_tokens':513},{'strategy':'fake'},{'offset':-1},{'limit':51},{'raw_source':'private'}]:
            assert (await c.post(route,json=payload)).status_code==422
    assert not s.calls
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(s,False)),base_url='http://test') as c:
        assert (await c.post(route,json={})).status_code==401

@pytest.mark.asyncio
async def test_scope_change_is_stable_409_without_original_content():
    s=Service();s.error=RetrievalError('CHUNK_SOURCE_CHANGED','资料变化',409)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(s)),base_url='http://test') as c:
        r=await c.post(f'/api/v1/owner/spaces/{SID}/documents/{DID}/chunk-preview',json={})
    assert r.status_code==409 and r.json()['code']=='CHUNK_SOURCE_CHANGED' and '原文' not in r.text
