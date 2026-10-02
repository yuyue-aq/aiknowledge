from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Sequence
from typing import Any

from app.services.token_budget import TokenBudget, TokenSlice


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
        batch_size: int = 8,
        timeout_seconds: float = 600.0,
        max_retries: int = 1,
        model_factory: ModelFactory | None = None,
    ) -> None:
        if expected_dimension <= 0:
            raise ValueError("expected_dimension must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")

        self._model_name = model_name
        self._expected_dimension = expected_dimension
        self._use_fp16 = use_fp16
        self._batch_size = batch_size
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._model_factory = model_factory or self._default_model_factory
        self._custom_factory = model_factory is not None
        self._model: object | None = None
        self._initialization_lock = asyncio.Lock()
        self._encoding_task: asyncio.Task | None = None

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts, encoder_name="encode_queries")

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts, encoder_name="encode_corpus")

    async def split_document_text(self, text: str) -> list[TokenSlice]:
        model = await self._get_model()
        budget = self._token_budget(model)
        if budget is None:
            raise EmbeddingBackendUnavailable('模型没有提供 tokenizer，无法验证资料长度。')
        return await asyncio.to_thread(budget.split, text, overlap_characters=240)

    def _token_budget(self, model: object) -> TokenBudget | None:
        tokenizer = getattr(model, 'tokenizer', None)
        if tokenizer is None:
            if self._custom_factory:
                # Legacy test ports may deliberately omit a real tokenizer.
                return None
            raise EmbeddingBackendUnavailable('向量模型未提供可用的 tokenizer。')
        config = getattr(getattr(model, 'model', None), 'config', None)
        capacity = min(512, int(getattr(config, 'max_position_embeddings', 512)))
        return TokenBudget(tokenizer, capacity=capacity)

    async def _embed(
        self, texts: Sequence[str], *, encoder_name: str
    ) -> list[list[float]]:
        normalized_texts = list(texts)
        if not normalized_texts:
            return []

        model = await self._get_model()
        budget = self._token_budget(model)
        if budget is not None:
            for text in normalized_texts:
                if encoder_name == 'encode_queries':
                    budget.validate_query(text, prefix=self.QUERY_INSTRUCTION)
                elif budget.count(text) > budget.capacity:
                    raise EmbeddingDimensionError('资料片段超过模型输入上限，需要重新分块。')
        encoder = getattr(model, encoder_name, None)
        if not callable(encoder):
            raise EmbeddingBackendUnavailable(
                f"The configured BGE backend does not provide {encoder_name}."
            )

        vectors: list[list[float]] = []
        for start in range(0, len(normalized_texts), self._batch_size):
            batch = normalized_texts[start : start + self._batch_size]
            raw_vectors = await self._encode_batch_with_retry(encoder, batch)
            validated = self._coerce_and_validate_vectors(raw_vectors)
            if len(validated) != len(batch):
                raise EmbeddingDimensionError('向量模型返回数量与输入不一致。')
            vectors.extend(validated)
        return vectors

    async def _encode_batch_with_retry(
        self, encoder: Callable[[Sequence[str]], Any], batch: Sequence[str]
    ) -> Any:
        for attempt in range(self._max_retries + 1):
            if self._encoding_task is not None and not self._encoding_task.done():
                raise EmbeddingBackendUnavailable('本地向量模型仍在处理，请稍后重试。')
            # A Python thread cannot be cancelled by wait_for. Retain and shield
            # it so timeout/cancellation never permits a second concurrent job.
            self._encoding_task = asyncio.create_task(asyncio.to_thread(encoder, batch))
            self._encoding_task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            try:
                return await asyncio.wait_for(
                    asyncio.shield(self._encoding_task), timeout=self._timeout_seconds
                )
            except asyncio.TimeoutError as exc:
                raise EmbeddingBackendUnavailable(
                    '本地向量模型处理超时，请稍后重试。'
                ) from exc
            except (RuntimeError, OSError) as exc:
                if attempt >= self._max_retries:
                    raise EmbeddingBackendUnavailable(
                        "本地向量模型暂时不可用，请稍后重试。"
                    ) from exc
            if attempt < self._max_retries:
                await asyncio.sleep(min(2**attempt, 4))
        raise AssertionError("embedding retry loop must return or raise")

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
            if not all(math.isfinite(x) for x in vector) or math.hypot(*vector) == 0:
                raise EmbeddingDimensionError("Embedding must contain finite non-zero values.")
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
            normalize_embeddings=True,
        )
