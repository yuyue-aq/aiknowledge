from dataclasses import replace
from hashlib import sha256
from uuid import uuid4
import pytest
from app.domain.documents import DocumentPermissionDeniedError,DocumentStatus,DocumentVersionStatus
from app.domain.users import SpaceRole
from app.services.chunk_plan import ChunkConfig
from app.services.document_ingestion import DocumentIngestionService,DocumentIngestionError
from app.services.document_workflow import DocumentAlreadyExistsError,DocumentProcessingService,ProcessingOutcome
from app.services.chunking import TextChunker
from app.services.token_budget import TokenBudget
from test_document_workflow import FakeStorage,FakeDispatcher,create_upload_service,FakeParser,FakeRepository,FakeIngestionService
from test_document_version_updates import VersionRepository
from test_document_management import build_records

@pytest.mark.asyncio
async def test_same_source_rebuild_is_allowed_only_for_same_document_and_records_config():
    repo=VersionRepository();storage=FakeStorage();content=b'same source'
    repo.document=replace(repo.document,sha256=sha256(content).hexdigest());repo.existing=repo.document
    cfg=ChunkConfig(max_tokens=128).snapshot()
    result=await create_upload_service(repo,storage,FakeDispatcher(repo)).upload(space_id=repo.document.space_id,
        category_id=repo.document.category_id,filename='资料.txt',content=content,content_type='text/plain',
        owner_user_id=uuid4(),_replacing_document=repo.document,_chunk_config=cfg)
    assert result.version.chunk_config==cfg and result.document.active_version_id==repo.document.active_version_id
    assert result.version.source_snapshot['requested_by_user_id']
    repo.existing=replace(repo.document,id=uuid4())
    with pytest.raises(DocumentAlreadyExistsError):await create_upload_service(repo,storage,FakeDispatcher(repo)).upload(
        space_id=repo.document.space_id,category_id=repo.document.category_id,filename='资料.txt',content=content,
        content_type='text/plain',owner_user_id=uuid4(),_replacing_document=repo.document,_chunk_config=cfg)

@pytest.mark.asyncio
async def test_editor_cannot_use_admin_rebuild_configuration_and_no_storage_written():
    repo=VersionRepository();repo.role=SpaceRole.EDITOR;storage=FakeStorage()
    with pytest.raises(DocumentPermissionDeniedError):await create_upload_service(repo,storage,FakeDispatcher(repo)).upload(
        space_id=repo.document.space_id,category_id=repo.document.category_id,filename='资料.txt',content=b'body',
        content_type='text/plain',owner_user_id=uuid4(),_replacing_document=repo.document,_chunk_config=ChunkConfig().snapshot())
    assert not storage.uploads

@pytest.mark.asyncio
async def test_configured_ingestion_matches_preview_and_invalid_fingerprint_never_embeds():
    from app.services.chunk_plan import plan_chunks
    parser=FakeParser();parsed=parser.parse(filename='资料.txt',content=b'body')
    class Encoder:
        calls=0
        async def document_token_budget(self):return TokenBudget(lambda x,**kw:{'input_ids':list(range(len(x)+2))},capacity=32)
        async def embed_documents(self,texts):self.calls+=1;return [[1.,2.,3.] for x in texts]
    enc=Encoder();cfg=ChunkConfig(max_tokens=16,overlap_characters=0)
    service=DocumentIngestionService(embedding_client=enc,chunker=TextChunker(),expected_embedding_dimension=3)
    result=await service.prepare(parsed,chunk_config=cfg.snapshot())
    expected=plan_chunks(parsed,await enc.document_token_budget(),cfg)
    assert [(x.content,x.char_start,x.char_end) for x in result.chunks]==[(x.content,x.char_start,x.char_end) for x in expected]
    broken={**cfg.snapshot(),'configuration_fingerprint':'invalid'}
    with pytest.raises(DocumentIngestionError):await service.prepare(parsed,chunk_config=broken)
    assert enc.calls==1

@pytest.mark.asyncio
async def test_worker_passes_frozen_config_and_config_failure_does_not_activate():
    doc,version=build_records();cfg=ChunkConfig().snapshot()
    version=replace(version,status=DocumentVersionStatus.PROCESSING,chunk_config=cfg)
    repo=FakeRepository();repo.context=(doc,version);storage=FakeStorage();storage.objects[doc.storage_key]=b'body'
    class Ingestion(FakeIngestionService):
        received=None
        async def prepare(self,parsed,**kwargs):
            self.received=kwargs['chunk_config'];return await super().prepare(parsed)
    ingestion=Ingestion();worker=DocumentProcessingService(repository=repo,storage=storage,parser=FakeParser(),ingestion_service=ingestion)
    assert await worker.process(version.id)==ProcessingOutcome.ACTIVATED and ingestion.received==cfg
    repo.activated=None;repo.context=(doc,version)
    class Invalid(Ingestion):
        async def prepare(self,parsed,**kwargs):raise DocumentIngestionError('bad fingerprint')
    worker=DocumentProcessingService(repository=repo,storage=storage,parser=FakeParser(),ingestion_service=Invalid())
    assert await worker.process(version.id)==ProcessingOutcome.FAILED and repo.activated is None
