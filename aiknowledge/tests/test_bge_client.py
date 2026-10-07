from __future__ import annotations

import pytest
import asyncio
from threading import Event

from app.infrastructure.embeddings.bge import (
    BgeEmbeddingClient,
    EmbeddingBackendUnavailable,
    EmbeddingDimensionError,
)
from app.domain.retrieval import RetrievalError


class CharacterTokenizer:
    def __call__(self, text, **kwargs):
        return {'input_ids': [0] * (len(text) + 2)}


@pytest.mark.asyncio
async def test_concurrent_encoding_waits_and_preserves_request_vectors():
    entered, release = Event(), Event()

    class QueuedModel(FakeFlagModel):
        def encode_queries(self, texts):
            self.query_calls.append(texts)
            if texts == ['第一请求']:
                entered.set()
                release.wait(timeout=5)
            return [[1., 0., 0.]] if texts == ['第一请求'] else [[0., 1., 0.]]

    model = QueuedModel()
    client = BgeEmbeddingClient(model_name='test', expected_dimension=3, timeout_seconds=2, model_factory=lambda **_: model)
    first = asyncio.create_task(client.embed_queries(['第一请求']))
    second = None
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        second = asyncio.create_task(client.embed_queries(['第二请求']))
        await asyncio.sleep(.03)
        assert not second.done()
        assert len(model.query_calls) == 1
        release.set()
        assert await first == [[1., 0., 0.]]
        assert await second == [[0., 1., 0.]]
        assert model.query_calls == [['第一请求'], ['第二请求']]
    finally:
        release.set()
        await first
        if second is not None:
            await asyncio.gather(second, return_exceptions=True)


@pytest.mark.asyncio
async def test_timed_out_local_encoding_is_not_retried_or_overlapped():
    entered, release = Event(), Event()

    class SlowModel(FakeFlagModel):
        def encode_queries(self, texts):
            self.query_calls.append(texts)
            entered.set()
            release.wait(timeout=5)
            return [[1., 0., 0.]]

    model = SlowModel()
    client = BgeEmbeddingClient(model_name='test', expected_dimension=3, timeout_seconds=.02, max_retries=2, model_factory=lambda **_: model)
    try:
        with pytest.raises(EmbeddingBackendUnavailable):
            await client.embed_queries(['第一请求'])
        assert entered.is_set()
        with pytest.raises(EmbeddingBackendUnavailable):
            await client.embed_queries(['第二请求'])
        assert len(model.query_calls) == 1
    finally:
        release.set()
        await asyncio.sleep(.05)


@pytest.mark.asyncio
async def test_embedding_rejects_wrong_batch_cardinality():
    class MissingModel(FakeFlagModel):
        def encode_corpus(self, texts):
            return []
    client = BgeEmbeddingClient(model_name='test', expected_dimension=3, model_factory=lambda **_: MissingModel())
    with pytest.raises(EmbeddingDimensionError):
        await client.embed_documents(['资料'])


async def test_bge_checks_query_prefix_before_encoding():
    model = FakeFlagModel()
    model.tokenizer = CharacterTokenizer()
    client = BgeEmbeddingClient(model_name='test', expected_dimension=3, model_factory=lambda **_: model)
    with pytest.raises(RetrievalError) as exc:
        await client.embed_queries(['问' * 500])
    assert exc.value.code == 'QUERY_TOKEN_LIMIT'
    assert model.query_calls == []


async def test_bge_splits_documents_without_losing_tail():
    model = FakeFlagModel()
    model.tokenizer = CharacterTokenizer()
    client = BgeEmbeddingClient(model_name='test', expected_dimension=3, model_factory=lambda **_: model)
    parts = await client.split_document_text('汉' * 1100 + '最后的证据')
    original = '汉' * 1100 + '最后的证据'
    restored = [''] * len(original)
    for part in parts:
        assert original[part.char_start:part.char_end] == part.content
        restored[part.char_start:part.char_end] = part.content
    assert ''.join(restored) == original
    assert parts[1].char_start < parts[0].char_end
    assert all(p.token_count <= 512 for p in parts)
    with pytest.raises(EmbeddingDimensionError):
        await client.embed_documents(['汉' * 600])


class FakeFlagModel:
    def __init__(self) -> None:
        self.query_calls: list[list[str]] = []
        self.corpus_calls: list[list[str]] = []

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        self.query_calls.append(texts)
        return [[0.2, 0.3, 0.4] for _ in texts]

    def encode_corpus(self, texts: list[str]) -> list[list[float]]:
        self.corpus_calls.append(texts)
        return [[0.1, 0.6, 0.7] for _ in texts]


@pytest.mark.parametrize('vector', [[0., 0., 0.], [float('nan'), 1., 0.], [float('inf'), 0., 1.]])
async def test_bge_rejects_invalid_numeric_vectors(vector):
    class InvalidModel(FakeFlagModel):
        def encode_corpus(self, texts):
            return [vector for _ in texts]
    client = BgeEmbeddingClient(model_name='test', expected_dimension=3, model_factory=lambda **_: InvalidModel())
    with pytest.raises(EmbeddingDimensionError):
        await client.embed_documents(['证据'])


@pytest.mark.asyncio
async def test_bge_client_uses_query_and_corpus_encoders() -> None:
    fake_model = FakeFlagModel()
    factory_arguments: dict[str, object] = {}

    def factory(**kwargs: object) -> FakeFlagModel:
        factory_arguments.update(kwargs)
        return fake_model

    client = BgeEmbeddingClient(
        model_name="BAAI/bge-large-zh-v1.5",
        expected_dimension=3,
        model_factory=factory,
    )

    assert await client.embed_queries(["如何上传资料？"]) == [[0.2, 0.3, 0.4]]
    assert await client.embed_documents(["上传说明"]) == [[0.1, 0.6, 0.7]]
    assert fake_model.query_calls == [["如何上传资料？"]]
    assert fake_model.corpus_calls == [["上传说明"]]
    assert factory_arguments["model_name"] == "BAAI/bge-large-zh-v1.5"
    assert factory_arguments["query_instruction_for_retrieval"] == "为这个句子生成表示以用于检索相关文章："


@pytest.mark.asyncio
async def test_bge_client_fails_closed_on_an_unexpected_vector_dimension() -> None:
    client = BgeEmbeddingClient(
        model_name="BAAI/bge-large-zh-v1.5",
        expected_dimension=4,
        model_factory=lambda **_: FakeFlagModel(),
    )

    with pytest.raises(EmbeddingDimensionError, match="expected 4"):
        await client.embed_queries(["测试"])


@pytest.mark.asyncio
async def test_bge_client_reports_a_missing_optional_backend() -> None:
    def unavailable_factory(**_: object) -> object:
        raise ImportError("FlagEmbedding is not installed")

    client = BgeEmbeddingClient(
        model_name="BAAI/bge-large-zh-v1.5",
        expected_dimension=1024,
        model_factory=unavailable_factory,
    )

    with pytest.raises(EmbeddingBackendUnavailable, match="local-embeddings"):
        await client.embed_documents(["测试"])


@pytest.mark.asyncio
async def test_bge_client_shards_document_batches() -> None:
    fake_model = FakeFlagModel()
    client = BgeEmbeddingClient(
        model_name="BAAI/bge-large-zh-v1.5",
        expected_dimension=3,
        batch_size=1,
        model_factory=lambda **_: fake_model,
    )

    vectors = await client.embed_documents(["第一段", "第二段"])

    assert len(vectors) == 2
    assert fake_model.corpus_calls == [["第一段"], ["第二段"]]


@pytest.mark.asyncio
async def test_bge_client_retries_a_transient_encoder_failure() -> None:
    class FlakyModel(FakeFlagModel):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def encode_corpus(self, texts: list[str]) -> list[list[float]]:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("temporary encoder failure")
            return super().encode_corpus(texts)

    model = FlakyModel()
    client = BgeEmbeddingClient(
        model_name="BAAI/bge-large-zh-v1.5",
        expected_dimension=3,
        max_retries=1,
        model_factory=lambda **_: model,
    )

    assert await client.embed_documents(["可重试文本"]) == [[0.1, 0.6, 0.7]]
    assert model.attempts == 2
