from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any


class EmbeddingBackendUnavailable(RuntimeError):
    """Raised when optional local BGE dependencies are not installed."""


class EmbeddingDimensionError(ValueError):
    """Raised when an embedding provider violates the configured contract."""


ModelFactory = Callable[..., object]


class BgeEmbeddingClient:
    """Lazy FlagEmbedding adapter for ``BAAI/bge-large-zh-v1.5``.

    Loading the model happens only on the first embedding call so API startup,
    test discovery, and settings validation do not download model weights.
    """

    QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

    def __init__(
        self,
        *,
        model_name: str,
        expected_dimension: int,
        use_fp16: bool = False,
        model_factory: ModelFactory | None = None,
    ) -> None:
        if expected_dimension <= 0:
            raise ValueError("expected_dimension must be positive")

        self._model_name = model_name
        self._expected_dimension = expected_dimension
        self._use_fp16 = use_fp16
        self._model_factory = model_factory or self._default_model_factory
        self._model: object | None = None
        self._initialization_lock = asyncio.Lock()

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts, encoder_name="encode_queries")

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts, encoder_name="encode_corpus")

    async def _embed(
        self, texts: Sequence[str], *, encoder_name: str
    ) -> list[list[float]]:
        normalized_texts = list(texts)
        if not normalized_texts:
            return []

        model = await self._get_model()
        encoder = getattr(model, encoder_name, None)
        if not callable(encoder):
            raise EmbeddingBackendUnavailable(
                f"The configured BGE backend does not provide {encoder_name}."
            )

        raw_vectors = await asyncio.to_thread(encoder, normalized_texts)
        return self._coerce_and_validate_vectors(raw_vectors)

    async def _get_model(self) -> object:
        if self._model is not None:
            return self._model

        async with self._initialization_lock:
            if self._model is None:
                try:
                    self._model = await asyncio.to_thread(
                        self._model_factory,
                        model_name=self._model_name,
                        query_instruction_for_retrieval=self.QUERY_INSTRUCTION,
                        use_fp16=self._use_fp16,
                    )
                except ImportError as exc:
                    raise EmbeddingBackendUnavailable(
                        "The local BGE backend is unavailable. Install it with "
                        "`uv sync --extra local-embeddings`."
                    ) from exc
        return self._model

    def _coerce_and_validate_vectors(self, raw_vectors: Any) -> list[list[float]]:
        if hasattr(raw_vectors, "tolist"):
            raw_vectors = raw_vectors.tolist()

        vectors: list[list[float]] = []
        for raw_vector in raw_vectors:
            if hasattr(raw_vector, "tolist"):
                raw_vector = raw_vector.tolist()
            vector = [float(value) for value in raw_vector]
            if len(vector) != self._expected_dimension:
                raise EmbeddingDimensionError(
                    f"Embedding dimension mismatch: expected {self._expected_dimension}, "
                    f"received {len(vector)}."
                )
            vectors.append(vector)
        return vectors

    @staticmethod
    def _default_model_factory(
        *,
        model_name: str,
        query_instruction_for_retrieval: str,
        use_fp16: bool,
    ) -> object:
        try:
            from FlagEmbedding import FlagModel
        except ImportError as exc:
            raise EmbeddingBackendUnavailable(
                "FlagEmbedding is not installed. Install the local-embeddings extra."
            ) from exc

        return FlagModel(
            model_name,
            query_instruction_for_retrieval=query_instruction_for_retrieval,
            use_fp16=use_fp16,
        )
