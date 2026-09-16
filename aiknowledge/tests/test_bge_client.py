from __future__ import annotations

import pytest

from app.infrastructure.embeddings.bge import (
    BgeEmbeddingClient,
    EmbeddingBackendUnavailable,
    EmbeddingDimensionError,
)


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
