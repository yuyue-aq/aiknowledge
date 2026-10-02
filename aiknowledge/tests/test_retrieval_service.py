from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from app.domain.conversations import RetrievedChunk
from app.domain.retrieval import RetrievalError
from app.services.retrieval import RetrievalService, cosine_similarity, top_k_vectors


def hit(number, score):
    return RetrievedChunk(id=UUID(int=number), document_id=uuid4(), document_name='说明.txt',
                          content=f'证据 {number}', page_number=3, ordinal=number, score=score)


class Encoder:
    def __init__(self, vector=None):
        self.vector = [1., 0., 0.] if vector is None else vector
        self.calls = []

    async def embed_queries(self, texts):
        self.calls.append(texts)
        return [self.vector]


def test_cosine_known_values_and_normalized_dot_product():
    assert cosine_similarity([3, 4], [4, 3]) == pytest.approx(.96)
    assert cosine_similarity([1, 0], [0, 1]) == 0
    assert cosine_similarity([1, 0], [-1, 0]) == -1
    assert cosine_similarity([.6, .8], [.8, .6]) == pytest.approx(.96)


@pytest.mark.parametrize('a,b', [([], []), ([1], [1, 2]), ([0, 0], [1, 0]),
                                ([float('nan')], [1]), ([float('inf')], [1])])
def test_cosine_rejects_invalid_vectors(a, b):
    with pytest.raises(ValueError):
        cosine_similarity(a, b)


def test_top_k_has_stable_ties_and_clamps_to_available_documents():
    assert top_k_vectors([1, 0], [[0, 1], [1, 0], [1, 0]], 10) == [(1, 1.), (2, 1.), (0, 0.)]
    assert top_k_vectors([1, 0], [], 2) == []
    with pytest.raises(ValueError):
        top_k_vectors([1, 0], [[1, 0]], 0)


async def test_search_encodes_once_returns_ranked_deduplicated_hits_without_llm():
    encoder = Encoder()
    calls = []
    async def fetch(vector, limit):
        calls.append((vector, limit))
        return [hit(3, .2), hit(2, .8), hit(1, .8), hit(1, .8)]
    result = await RetrievalService(encoder, expected_dimension=3).search(
        question='  访客范围？  ', fetch=fetch, top_k=2)
    assert encoder.calls == [['访客范围？']]
    assert calls == [([1., 0., 0.], 2)]
    assert [x.id.int for x in result.items] == [1, 2]
    assert result.question == '访客范围？'
    assert result.timings_ms.keys() == {'embedding', 'search', 'total'}


@pytest.mark.parametrize('question,k', [('', 4), ('  ', 4), ('x'*2001, 4), ('问题', 0), ('问题', 21), ('问题', True)])
async def test_invalid_request_does_not_invoke_embedding(question, k):
    encoder = Encoder()
    async def fetch(vector, limit):
        pytest.fail('invalid input must not query repository')
    with pytest.raises(RetrievalError) as exc:
        await RetrievalService(encoder, expected_dimension=3).search(question=question, fetch=fetch, top_k=k)
    assert exc.value.code == 'RETRIEVAL_INPUT_INVALID'
    assert encoder.calls == []


@pytest.mark.parametrize('vector', [[1, 0], [0, 0, 0], [float('nan'), 0, 1], [float('inf'), 0, 1]])
async def test_invalid_embedding_never_reaches_database(vector):
    async def fetch(vector, limit):
        pytest.fail('invalid vector must not reach database')
    with pytest.raises(RetrievalError) as exc:
        await RetrievalService(Encoder(vector), expected_dimension=3).search(question='问题', fetch=fetch)
    assert exc.value.code == 'EMBEDDING_INVALID'


async def test_empty_result_is_success_but_database_failure_is_not_empty():
    async def empty(vector, limit):
        return []
    service = RetrievalService(Encoder(), expected_dimension=3)
    assert (await service.search(question='问题', fetch=empty)).items == ()
    async def broken(vector, limit):
        raise RuntimeError('private connection details')
    with pytest.raises(RetrievalError) as exc:
        await service.search(question='问题', fetch=broken)
    assert exc.value.code == 'RETRIEVAL_UNAVAILABLE'
    assert 'private' not in str(exc.value)


async def test_embedding_outage_has_separate_error_code():
    class BrokenEncoder:
        async def embed_queries(self, texts):
            raise RuntimeError('secret provider response')
    async def fetch(vector, limit):
        pytest.fail('must not search after embedding failure')
    with pytest.raises(RetrievalError) as exc:
        await RetrievalService(BrokenEncoder()).search(question='问题', fetch=fetch)
    assert exc.value.code == 'EMBEDDING_UNAVAILABLE'


async def test_invalid_repository_score_is_not_exposed():
    async def fetch(vector, limit):
        return [replace(hit(1, .8), score=float('nan'))]
    with pytest.raises(RetrievalError) as exc:
        await RetrievalService(Encoder(), expected_dimension=3).search(question='问题', fetch=fetch)
    assert exc.value.code == 'RETRIEVAL_UNAVAILABLE'
