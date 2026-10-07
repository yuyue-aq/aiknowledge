from dataclasses import replace, asdict
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.documents import DocumentStatus, DocumentVersionStatus, DocumentPermissionDeniedError
from app.domain.users import SpaceRole
from app.services.document_workflow import DocumentUploadService
from test_document_workflow import FakeRepository, FakeStorage, FakeDispatcher, create_upload_service
from test_document_management import build_records
from test_document_repository import FakeSession
from app.infrastructure.database.document_repository import SqlAlchemyDocumentRepository
from app.infrastructure.database.models import DocumentRecord, DocumentVersionRecord
import httpx
from app.main import create_app
from app.api.dependencies import get_current_user, get_database_session
from app.core.config import Settings
from app.domain.documents import DocumentSubmission


class VersionRepository(FakeRepository):
    def __init__(self):
        super().__init__()
        document, version = build_records()
        self.document = replace(document, status=DocumentStatus.READY, active_version_id=version.id)
        self.version = replace(version, status=DocumentVersionStatus.READY)
        self.role = SpaceRole.OWNER
        self.replacement = None

    async def get_document(self, document_id):
        return self.document if self.document.id == document_id else None

    async def get_space_role(self, **kwargs):
        return self.role

    async def create_replacement_version(self, document, version):
        self.replacement = replace(version, version_number=2)
        return self.replacement


@pytest.mark.asyncio
async def test_replacement_keeps_old_source_and_active_version_until_processing_succeeds():
    repository, storage = VersionRepository(), FakeStorage()
    storage.objects[repository.document.storage_key] = b'old source'
    dispatcher = FakeDispatcher(repository)
    service = create_upload_service(repository, storage, dispatcher)
    result = await service.replace_document(repository.document.id, filename='新资料.txt', content=b'new source',
        content_type='text/plain', owner_user_id=uuid4())
    assert result.document == repository.document
    assert result.version.version_number == 2
    assert result.version.document_id == repository.document.id
    assert result.version.source_snapshot['storage_key'] != repository.document.storage_key
    assert storage.objects[repository.document.storage_key] == b'old source'
    assert storage.objects[result.version.source_snapshot['storage_key']] == b'new source'
    assert repository.document.active_version_id == repository.version.id
    assert repository.document.status is DocumentStatus.READY
    assert dispatcher.enqueued == [result.version.id]
    assert dispatcher.commit_count_when_enqueued == 1


@pytest.mark.asyncio
async def test_member_cannot_upload_a_replacement_or_write_new_object():
    repository, storage = VersionRepository(), FakeStorage()
    repository.role = SpaceRole.MEMBER
    service = create_upload_service(repository, storage, FakeDispatcher(repository))
    with pytest.raises(DocumentPermissionDeniedError):
        await service.replace_document(repository.document.id, filename='新资料.txt', content=b'new source',
            content_type='text/plain', owner_user_id=uuid4())
    assert storage.objects == {}
    assert repository.replacement is None


@pytest.mark.asyncio
async def test_replacement_transaction_failure_removes_only_the_new_object():
    repository, storage = VersionRepository(), FakeStorage()
    storage.objects[repository.document.storage_key] = b'old source'
    async def conflict(*args):
        raise ValueError('新版本正在处理中')
    repository.create_replacement_version = conflict
    service = create_upload_service(repository, storage, FakeDispatcher(repository))
    with pytest.raises(ValueError, match='处理中'):
        await service.replace_document(repository.document.id, filename='新资料.txt', content=b'new source',
            content_type='text/plain', owner_user_id=uuid4())
    assert storage.objects == {repository.document.storage_key: b'old source'}


@pytest.mark.asyncio
async def test_processing_reads_new_version_source_but_current_document_switches_only_on_activation():
    document, version = build_records()
    document = replace(document, status=DocumentStatus.READY, active_version_id=uuid4())
    source = {'storage_key': 'new-version/source.txt', 'original_filename': '更新.txt', 'mime_type': 'text/plain', 'size_bytes': 12, 'sha256': 'b'*64}
    version = replace(version, status=DocumentVersionStatus.PROCESSING, source_snapshot=source)
    session = FakeSession()
    current = DocumentRecord(**asdict(document))
    session.add(current)
    session.add(DocumentVersionRecord(**asdict(version)))
    async def execute(statement):
        return SimpleNamespace()
    session.execute = execute
    repo = SqlAlchemyDocumentRepository(session)
    processing, saved = await repo.get_processing_context(version.id)
    assert processing.storage_key == source['storage_key']
    assert saved.source_snapshot == source
    assert current.storage_key == document.storage_key
    assert current.active_version_id == document.active_version_id
    await repo.activate_processed_version(version_id=version.id, chunks=())
    assert current.storage_key == source['storage_key']
    assert current.sha256 == source['sha256']
    assert current.original_filename == source['original_filename']
    assert current.active_version_id == version.id


@pytest.mark.asyncio
async def test_cleanup_scan_is_bounded_deleted_only_and_includes_historical_sources():
    from datetime import datetime, UTC
    document, version = build_records()
    document = replace(document, status=DocumentStatus.DELETED, deleted_at=datetime.now(UTC))
    session = FakeSession()
    current = DocumentRecord(**asdict(document))
    statements = []
    values = iter([[current], [SimpleNamespace(source_snapshot={'storage_key': 'historical/source.txt'}), SimpleNamespace(source_snapshot={'storage_key': document.storage_key})]])
    async def scalars(statement):
        statements.append(str(statement))
        return SimpleNamespace(all=lambda: next(values))
    session.scalars = scalars
    session.add(current)
    repo = SqlAlchemyDocumentRepository(session)
    result = await repo.list_pending_cleanup(20)
    assert result == [(document.id, [document.storage_key, 'historical/source.txt'])]
    assert 'deleted_at IS NOT NULL' in statements[0]
    assert 'cleanup_completed_at IS NULL' in statements[0]
    assert 'LIMIT' in statements[0]
    await repo.mark_cleanup_completed(document.id)
    assert current.cleanup_completed_at is not None


@pytest.mark.asyncio
async def test_replacement_version_number_is_allocated_under_document_lock_without_early_switch():
    document, version = build_records()
    document = replace(document, status=DocumentStatus.READY, active_version_id=version.id)
    new_version = replace(version, id=uuid4(), status=DocumentVersionStatus.PROCESSING)
    session = FakeSession()
    current = DocumentRecord(**asdict(document))
    session.add(current)
    values = iter([None, 1])
    async def scalar(statement):
        return next(values)
    session.scalar = scalar
    saved = await SqlAlchemyDocumentRepository(session).create_replacement_version(document, new_version)
    assert saved.version_number == 2
    assert current.active_version_id == document.active_version_id
    assert current.status is DocumentStatus.READY


@pytest.mark.asyncio
async def test_version_upload_api_requires_auth_and_returns_old_ready_document_with_new_job():
    repository = VersionRepository()
    calls = []
    user_id = uuid4()
    async def update(document_id, **kwargs):
        calls.append((document_id, kwargs))
        return DocumentSubmission(repository.document, replace(repository.version, id=uuid4(), status=DocumentVersionStatus.PROCESSING), True)
    app = create_app(settings=Settings(auth_required=False), document_service_factory=lambda _: SimpleNamespace(replace_document=update))
    async def session():
        yield None
    app.dependency_overrides[get_database_session] = session
    url = f'/api/v1/documents/{repository.document.id}/versions'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post(url, files={'file': ('更新.txt', b'new', 'text/plain')})).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
        response = await client.post(url, files={'file': ('更新.txt', b'new', 'text/plain')})
    assert response.status_code == 202
    assert response.json()['document']['status'] == 'READY'
    assert response.json()['document']['active_version_id'] == str(repository.document.active_version_id)
    assert calls[0][1]['owner_user_id'] == user_id
    assert calls[0][1]['content'] == b'new'


@pytest.mark.asyncio
async def test_retry_replacement_preserves_current_document_and_commits_before_queue():
    from app.services.document_management import DocumentManagementService
    repository = VersionRepository()
    repository.retry_failed_version = lambda *args: None
    async def retry(document_id, version_id):
        return repository.document, replace(repository.version, status=DocumentVersionStatus.PROCESSING)
    repository.retry_failed_version = retry
    dispatcher = FakeDispatcher(repository)
    submission = await DocumentManagementService(repository=repository, dispatcher=dispatcher).retry_version(
        repository.document.id, repository.version.id, owner_user_id=uuid4())
    assert submission.document.status is DocumentStatus.READY
    assert submission.document.active_version_id == repository.document.active_version_id
    assert submission.processing_enqueued is True
    assert dispatcher.commit_count_when_enqueued == 1


@pytest.mark.asyncio
async def test_repository_retries_failed_replacement_without_switching_active_version():
    document, version = build_records()
    document = replace(document, status=DocumentStatus.READY, active_version_id=uuid4())
    session = FakeSession()
    current = DocumentRecord(**asdict(document))
    session.add(current)
    version = replace(version, source_snapshot={'storage_key': 'new/source.txt'})
    session.add(DocumentVersionRecord(**asdict(version)))
    async def scalar(statement):
        return None
    session.scalar = scalar
    result = await SqlAlchemyDocumentRepository(session).retry_failed_version(document.id, version.id)
    assert result[1].status is DocumentVersionStatus.PROCESSING
    assert current.status is DocumentStatus.READY
    assert current.active_version_id == document.active_version_id


@pytest.mark.asyncio
async def test_retry_rejects_historical_failure_without_a_provable_source():
    document, version = build_records()
    document = replace(document, status=DocumentStatus.READY, active_version_id=uuid4())
    session = FakeSession()
    session.add(DocumentRecord(**asdict(document)))
    session.add(DocumentVersionRecord(**asdict(version)))
    async def scalar(statement): return None
    session.scalar = scalar
    assert await SqlAlchemyDocumentRepository(session).retry_failed_version(document.id, version.id) is None
