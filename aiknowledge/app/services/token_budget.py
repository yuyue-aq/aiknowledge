from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.domain.retrieval import RetrievalError


@dataclass(frozen=True, slots=True)
class TokenSlice:
    content: str
    char_start: int
    char_end: int
    token_count: int


class TokenBudget:
    """Never decode/rewrite source text or silently truncate encoded evidence."""

    def __init__(self, tokenizer: Callable, *, capacity: int = 512):
        if capacity < 1:
            raise ValueError('token capacity must be positive')
        self.tokenizer, self.capacity = tokenizer, capacity

    def count(self, text: str) -> int:
        return len(self.tokenizer(text, add_special_tokens=True, truncation=False)['input_ids'])

    def validate_query(self, text: str, *, prefix: str = '') -> None:
        if self.count(prefix + text) > self.capacity:
            raise RetrievalError('QUERY_TOKEN_LIMIT', '问题超过向量模型输入上限，请精简后重试。', 422)

    def split(self, text: str, *, overlap_characters: int = 0) -> list[TokenSlice]:
        if overlap_characters < 0:
            raise ValueError('overlap must not be negative')
        if not text.strip():
            return []
        result = []
        start = 0
        covered_end = 0
        while start < len(text):
            low, high = 1, min(1800, len(text)-start)
            best = 0
            while low <= high:
                size = (low+high)//2
                if self.count(text[start:start+size]) <= self.capacity:
                    best, low = size, size+1
                else:
                    high = size-1
            if not best:
                raise ValueError('单个字符无法在模型输入预算内编码。')
            end = start+best
            # Prefer a sentence boundary when it leaves a reasonably full block.
            segment = text[start:end]
            boundary = max(segment.rfind(c) for c in ('。', '！', '？', '\n'))+1
            if boundary >= best//2 and boundary > 0 and start+boundary > covered_end and self.count(text[start:start+boundary])<=self.capacity:
                end = start+boundary
            content = text[start:end]
            result.append(TokenSlice(content, start, end, self.count(content)))
            covered_end = end
            if end == len(text):
                break
            start = end-min(overlap_characters, (end-start)//2)
        return result
