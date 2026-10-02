from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.conversations import RetrievedChunk
from app.domain.retrieval import RetrievalError, RetrievalScope
from app.services.retrieval import RetrievalService
from app.services.owner_retrieval import OwnerRetrievalService


class Encoder:
    calls = 0

    async def embed_queries(self, texts):
        self.calls += 1
        return [[1., 0., 0.]]


@pytest.mark.asyncio
async def test_saved_evidence_reads_only_current_candidates_without_encoding():
    repo, encoder = Repository(), Encoder()
    missing = uuid4()
    items, unavailable = await service(repo, encoder).read_saved_evidence(space_id=repo.space_id, user_id=repo.user_id,
        chunk_ids=(repo.chunk.id, missing))
    assert [item.id for item in items] == [repo.chunk.id]
    assert unavailable == (missing,)
    assert encoder.calls == 0

class Repository:
    def __init__(self):
        self.user_id, self.space_id = uuid4(), uuid4()
        self.scope = RetrievalScope(self.space_id, self.user_id, 0, 0, datetime.now(UTC))
        self.allowed = True
        self.changed = False
        self.runs = {}
        self.chunk = RetrievedChunk(uuid4(), uuid4(), '资料.md', '证据', None, 1, .9)
        self.visible = True

    async def resolve_owner_scope(self, *, space_id, user_id):
        if not self.allowed or space_id != self.space_id or user_id != self.user_id:
            return None
        return self.scope

    async def retrieve(self, *, scope, embedding, limit):
        if self.changed:
            self.scope = replace(self.scope, knowledge_revision=1)
        return [self.chunk]

    async def add_run(self, run):
        self.runs[run.id] = run

    async def get_run(self, run_id):
        return self.runs.get(run_id)

    async def get_current_chunks(self, *, scope, chunk_ids):
        return [self.chunk] if self.visible else []


def service(repo, encoder):
    return OwnerRetrievalService(repository=repo, retrieval=RetrievalService(encoder, expected_dimension=3), model_name='test-bge')


@pytest.mark.asyncio
async def test_document_detail_requires_owner_and_never_encodes_or_returns_cross_space_content():
    repo, encoder = Repository(), Encoder()
    calls = []
    async def detail(**kwargs):
        calls.append(kwargs)
        return {'document': {'id': str(repo.chunk.document_id)}, 'versions': [], 'chunks': [repo.chunk]}
    repo.get_document_detail = detail
    with pytest.raises(RetrievalError):
        await service(repo, encoder).get_document_detail(space_id=repo.space_id, document_id=repo.chunk.document_id, user_id=uuid4())
    assert calls == []
    result = await service(repo, encoder).get_document_detail(space_id=repo.space_id, document_id=repo.chunk.document_id, user_id=repo.user_id)
    assert result['chunks'] == [repo.chunk]
    assert encoder.calls == 0


@pytest.mark.asyncio
async def test_document_detail_drops_raw_content_if_scope_changes_during_read():
    repo, encoder = Repository(), Encoder()
    async def detail(**kwargs):
        repo.scope = replace(repo.scope, knowledge_revision=1)
        return {'document': {'id': str(repo.chunk.document_id)}, 'versions': [], 'chunks': [repo.chunk]}
    repo.get_document_detail = detail
    with pytest.raises(RetrievalError) as error:
        await service(repo, encoder).get_document_detail(space_id=repo.space_id, document_id=repo.chunk.document_id, user_id=repo.user_id)
    assert error.value.code == 'RETRIEVAL_SCOPE_CHANGED'


@pytest.mark.asyncio
@pytest.mark.parametrize('allowed', [False, True])
async def test_owner_scope_is_resolved_before_model_calls(allowed):
    repo, encoder = Repository(), Encoder()
    repo.allowed = allowed
    user = repo.user_id if not allowed else uuid4()
    with pytest.raises(RetrievalError) as error:
        await service(repo, encoder).search(space_id=repo.space_id, user_id=user, question='问题', top_k=4)
    assert error.value.status_code == 404
    assert encoder.calls == 0
    assert not repo.runs


@pytest.mark.asyncio
async def test_scope_change_prevents_recording_or_returning_stale_evidence():
    repo, encoder = Repository(), Encoder()
    repo.changed = True
    with pytest.raises(RetrievalError) as error:
        await service(repo, encoder).search(space_id=repo.space_id, user_id=repo.user_id, question='问题', top_k=4)
    assert error.value.code == 'RETRIEVAL_SCOPE_CHANGED'
    assert error.value.status_code == 409
    assert not repo.runs


@pytest.mark.asyncio
async def test_run_persists_only_ids_scores_and_config_and_resolves_current_evidence():
    repo, encoder = Repository(), Encoder()
    app = service(repo, encoder)
    run, result = await app.search(space_id=repo.space_id, user_id=repo.user_id, question=' 问题 ', top_k=4)
    assert result.question == '问题'
    assert run.chunk_ids == (repo.chunk.id,)
    assert run.scores == (.9,)
    assert run.model_name == 'test-bge'
    assert not hasattr(run, 'content')
    saved, current = await app.get_run(run.id, user_id=repo.user_id)
    assert saved == run
    assert current == (repo.chunk,)
    repo.visible = False
    _, current = await app.get_run(run.id, user_id=repo.user_id)
    assert current == ()
    with pytest.raises(RetrievalError):
        await app.get_run(run.id, user_id=uuid4())


@pytest.mark.asyncio
async def test_time_expiration_is_checked_even_without_revision_change():
    repo, encoder = Repository(), Encoder()
    repo.visible = False
    with pytest.raises(RetrievalError) as error:
        await service(repo, encoder).search(space_id=repo.space_id, user_id=repo.user_id, question='问题', top_k=4)
    assert error.value.code == 'RETRIEVAL_SCOPE_CHANGED'
    assert not repo.runs
