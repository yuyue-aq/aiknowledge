from dataclasses import replace,asdict
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.domain.documents import DocumentVersionConflictError,DocumentVersionStatus,DocumentPermissionDeniedError
from app.domain.users import SpaceRole
from app.infrastructure.database.models import DocumentRecord,DocumentVersionRecord
from app.infrastructure.database.document_repository import SqlAlchemyDocumentRepository
from app.services.chunk_plan import ChunkConfig
from app.services.document_management import DocumentManagementService
from app.services.token_budget import TokenBudget
from test_document_management import build_records
from test_document_repository import FakeSession
from test_document_version_updates import VersionRepository
from test_document_workflow import FakeDispatcher

def test_nonmonotonic_tokenizer_never_overflows_on_sentence_boundary():
    source='abcde。EFGH'
    def tokenizer(text,**kwargs):return {'input_ids':list(range(30 if text=='abcde。' else len(text)+2))}
    result=TokenBudget(tokenizer,capacity=16).split(source)
    assert all(x.token_count<=16 for x in result) and ''.join(x.content for x in result)==source

@pytest.mark.asyncio
async def test_activation_rejects_stale_rebuild_base_before_any_chunk_write():
    document,version=build_records();base=uuid4()
    document=replace(document,active_version_id=uuid4())
    version=replace(version,status=DocumentVersionStatus.PROCESSING,chunk_config=ChunkConfig().snapshot(),source_snapshot={'base_active_version_id':str(base)})
    session=FakeSession();session.add(DocumentRecord(**asdict(document)));session.add(DocumentVersionRecord(**asdict(version)))
    async def execute(s):raise AssertionError('Must reject before changing any active chunk')
    session.execute=execute
    with pytest.raises(DocumentVersionConflictError):await SqlAlchemyDocumentRepository(session).activate_processed_version(version_id=version.id,chunks=())

@pytest.mark.asyncio
async def test_admin_rebuild_retry_cannot_be_triggered_by_editor():
    repo=VersionRepository();repo.role=SpaceRole.EDITOR
    repo.context=(repo.document,replace(repo.version,status=DocumentVersionStatus.FAILED,chunk_config=ChunkConfig().snapshot()))
    async def retry(*args,**kw):raise AssertionError('Must reject before retry mutation')
    repo.retry_failed_version=retry
    service=DocumentManagementService(repository=repo,dispatcher=FakeDispatcher(repo))
    with pytest.raises(DocumentPermissionDeniedError):await service.retry_version(repo.document.id,repo.version.id,owner_user_id=uuid4())
