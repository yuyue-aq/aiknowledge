from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Sequence
from time import perf_counter
from typing import Protocol

from app.domain.conversations import RetrievedChunk
from app.domain.retrieval import RetrievalError, RetrievalResult


class QueryEncoder(Protocol):
    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]: ...


FetchAuthorized = Callable[[list[float], int], Awaitable[list[RetrievedChunk]]]


def _vector(values: Sequence[float], dimension: int | None = None) -> list[float]:
    result = [float(x) for x in values]
    if not result or (dimension is not None and len(result) != dimension):
        raise ValueError('向量维度无效。')
    if not all(math.isfinite(x) for x in result) or math.hypot(*result) == 0:
        raise ValueError('向量必须为非零有限数值。')
    return result


def cosine_similarity(query: Sequence[float], document: Sequence[float]) -> float:
    q = _vector(query)
    d = _vector(document, len(q))
    qnorm, dnorm = math.hypot(*q), math.hypot(*d)
    return max(-1., min(1., math.fsum((a/qnorm)*(b/dnorm) for a, b in zip(q, d))))


def top_k_vectors(query: Sequence[float], documents: Sequence[Sequence[float]], k: int) -> list[tuple[int, float]]:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError('K 必须为正整数。')
    _vector(query)
    ranked = [(i, cosine_similarity(query, d)) for i, d in enumerate(documents)]
    return sorted(ranked, key=lambda x: (-x[1], x[0]))[:k]


class RetrievalService:
    """Encode once, query an already-authorized repository, never generate text.

    API/application callers resolve permissions before providing fetch. The
    callback must enforce those constraints in SQL, not filter a global search.
    """

    def __init__(self, encoder: QueryEncoder, *, expected_dimension: int | None = 1024, maximum_k: int = 20):
        self._encoder = encoder
        self._dimension = expected_dimension
        self._maximum_k = maximum_k

    async def search(self, *, question: str, fetch: FetchAuthorized, top_k: int = 4) -> RetrievalResult:
        if not isinstance(question, str) or not question.strip() or len(question.strip()) > 2000:
            raise RetrievalError('RETRIEVAL_INPUT_INVALID', '请输入 1—2000 字的问题。', 422)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= self._maximum_k:
            raise RetrievalError('RETRIEVAL_INPUT_INVALID', f'Top K 必须为 1—{self._maximum_k} 的整数。', 422)
        question = question.strip()
        started = perf_counter()
        try:
            vectors = await self._encoder.embed_queries([question])
        except RetrievalError:
            raise
        except Exception as exc:
            raise RetrievalError('EMBEDDING_UNAVAILABLE', '向量模型暂时不可用，请稍后重试。') from exc
        try:
            if len(vectors) != 1:
                raise ValueError('exactly one query vector required')
            vector = _vector(vectors[0], self._dimension)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RetrievalError('EMBEDDING_INVALID', '向量模型返回的数据无效。') from exc
        encoded = perf_counter()
        try:
            candidates = await fetch(vector, top_k)
            unique: dict[object, RetrievedChunk] = {}
            for item in candidates:
                if not math.isfinite(item.score) or not -1.000001 <= item.score <= 1.000001:
                    raise ValueError('invalid cosine score')
                previous = unique.get(item.id)
                if previous is None or previous.score < item.score:
                    unique[item.id] = item
            items = tuple(sorted(unique.values(), key=lambda x: (-x.score, str(x.id)))[:top_k])
        except Exception as exc:
            raise RetrievalError('RETRIEVAL_UNAVAILABLE', '检索服务暂时不可用，请稍后重试。') from exc
        completed = perf_counter()
        return RetrievalResult(question, top_k, items, {
            'embedding': round((encoded-started)*1000, 3),
            'search': round((completed-encoded)*1000, 3),
            'total': round((completed-started)*1000, 3),
        })
