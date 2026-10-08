from datetime import UTC, datetime
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.api.dependencies import get_current_user, get_database_session
from app.core.config import Settings
from app.domain.conversations import RetrievedChunk
from app.domain.retrieval import RetrievalError, RetrievalResult, RetrievalRun, RetrievalScope
from app.main import create_app


class Service:
    def __init__(self):
        self.user_id, self.space_id = uuid4(), uuid4()
        self.calls = []
        self.error = None
        now = datetime.now(UTC)
        scope = RetrievalScope(self.space_id, self.user_id, 2, 3, now)
        chunk = RetrievedChunk(uuid4(), uuid4(), '来源.txt', '原文证据', 2, 1, .96)
        self.result = RetrievalResult('问题', 4, (chunk,), {'total': 10.})
        self.run = RetrievalRun(uuid4(), scope, '问题', 4, (chunk.id,), (.96,), {'total': 10.}, 'bge', now)

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.run, self.result

    async def get_run(self, run_id, **kwargs):
        self.calls.append(kwargs)
        return self.run, self.result.items






def make_app(service, authenticated=True):
    app = create_app(settings=Settings(auth_required=False), retrieval_service_factory=lambda session: service)

    async def session():
        yield None

    app.dependency_overrides[get_database_session] = session
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=service.user_id)
    return app


@pytest.mark.asyncio
async def test_document_detail_endpoint_is_strictly_authenticated_and_hides_storage_fields():
    service = Service()
    document_id = service.result.items[0].document_id
    now = datetime.now(UTC).isoformat()
    async def detail(**kwargs):
        service.calls.append(kwargs)
        return {'document': {'id': document_id, 'space_id': service.space_id, 'owner_user_id': service.user_id,
            'category_id': None, 'original_filename': '资料.txt', 'mime_type': 'text/plain', 'size_bytes': 12,
            'status': 'READY', 'active_version_id': None, 'failure_code': None, 'failure_message': None,
            'is_enabled': True, 'effective_at': None, 'expires_at': None, 'created_at': now, 'updated_at': now,
            'storage_key': 'private-source-key'}, 'versions': [], 'chunks': service.result.items}
    service.get_document_detail = detail
    path = f'/api/v1/owner/spaces/{service.space_id}/documents/{document_id}'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(service, False)), base_url='http://test') as client:
        assert (await client.get(path)).status_code == 401
    assert service.calls == []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(service)), base_url='http://test') as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert response.json()['chunks'][0]['content'] == '原文证据'
    assert 'storage_key' not in response.json()['document']


@pytest.mark.asyncio
async def test_owner_diagnostics_require_auth_even_in_legacy_mode():
    service = Service()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(service, False)), base_url='http://test') as client:
        response = await client.post(f'/api/v1/owner/spaces/{service.space_id}/retrieval-runs', json={'question': '问题'})
    assert response.status_code == 401
    assert service.calls == []


@pytest.mark.asyncio
async def test_retrieval_api_returns_real_rank_score_and_current_sources():
    service = Service()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(service)), base_url='http://test') as client:
        response = await client.post(f'/api/v1/owner/spaces/{service.space_id}/retrieval-runs', json={'question': '问题', 'top_k': 4})
        detail = await client.get(f'/api/v1/owner/retrieval-runs/{service.run.id}')
    assert response.status_code == 201
    data = response.json()
    assert data['run_id'] == str(service.run.id)
    assert data['status'] == 'COMPLETED'
    assert data['knowledge_revision'] == 3
    assert data['items'][0]['rank'] == 1
    assert data['items'][0]['score'] == .96
    assert data['items'][0]['content'] == '原文证据'
    assert data['items'][0]['document_version_id'] is None
    assert service.calls[0]['user_id'] == service.user_id
    assert detail.status_code == 200
    assert detail.json()['items'][0]['rank'] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{'question': ' '}, {'question': '问题', 'top_k': True}, {'question': '问题', 'top_k': 21}, {'question': '问题', 'top_k': '4'}])
async def test_invalid_retrieval_input_never_reaches_service(payload):
    service = Service()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(service)), base_url='http://test') as client:
        response = await client.post(f'/api/v1/owner/spaces/{service.space_id}/retrieval-runs', json=payload)
    assert response.status_code == 422
    assert not service.calls


@pytest.mark.asyncio
async def test_retrieval_error_preserves_stable_code_and_safe_message():
    service = Service()
    service.error = RetrievalError('RETRIEVAL_SCOPE_CHANGED', '资料范围已变化，请重新检索。', 409)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(service)), base_url='http://test') as client:
        response = await client.post(f'/api/v1/owner/spaces/{service.space_id}/retrieval-runs', json={'question': '问题'})
    assert response.status_code == 409
    assert response.json()['code'] == 'RETRIEVAL_SCOPE_CHANGED'


@pytest.mark.asyncio
async def test_bm25_api_preserves_non_cosine_score_and_exposes_strategy():
    service=Service()
    service.run=replace(service.run,strategy='bm25',scores=(3.2,),config_snapshot={'analyzer':'zh-bigram-identifiers-v1'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(service)),base_url='http://test') as client:
        response=await client.post(f'/api/v1/owner/spaces/{service.space_id}/retrieval-runs',json={'question':'SCOPE_CHANGED','strategy':'bm25'})
        invalid=await client.post(f'/api/v1/owner/spaces/{service.space_id}/retrieval-runs',json={'question':'x','strategy':'hybrid'})
    assert response.status_code==201
    assert service.calls[0]['strategy']=='bm25'
    assert response.json()['strategy']=='bm25'
    assert response.json()['items'][0]['score']==3.2
    assert response.json()['items'][0]['score_kind']=='bm25'
    assert invalid.status_code==422


@pytest.mark.asyncio
async def test_eval_evidence_uses_saved_ids_and_scores_and_marks_missing_sources():
    from app.api.v1.evaluations import get_evaluation_service
    service = Service()
    result_id, missing = uuid4(), uuid4()
    snapshot = {'retrieved_chunks': [{'chunk_id': str(service.result.items[0].id), 'rank': 1, 'score': .87},
        {'chunk_id': str(missing), 'rank': 2, 'score': .8}]}
    async def run(run_id, **kwargs):
        assert kwargs['owner_user_id'] == service.user_id
        return SimpleNamespace(run=SimpleNamespace(space_id=service.space_id), results=[SimpleNamespace(id=result_id, execution_snapshot=snapshot)])
    async def evidence(**kwargs):
        assert kwargs['chunk_ids'] == (service.result.items[0].id, missing)
        return service.result.items, (missing,)
    service.read_saved_evidence = evidence
    app = make_app(service)
    app.dependency_overrides[get_evaluation_service] = lambda: SimpleNamespace(get_run=run)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get(f'/api/v1/owner/eval-runs/{uuid4()}/results/{result_id}/evidence')
    assert response.status_code == 200
    assert response.json()['items'][0]['score'] == .87
    assert response.json()['unavailable_chunk_ids'] == [str(missing)]
