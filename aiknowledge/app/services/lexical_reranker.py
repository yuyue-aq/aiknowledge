"""Keyword reranking of already-authorized dense candidates, without I/O."""
from collections import Counter
from math import log
import re
from typing import Sequence

from app.domain.rag import RankedSourceChunk


def _terms(text: str) -> list[str]:
    terms = []
    for word in re.findall(r'[a-z0-9_]+|[\u3400-\u9fff]+', text.lower()):
        if re.fullmatch(r'[a-z0-9_]+', word) or len(word) == 1:
            terms.append(word)
        else:
            terms.extend(word[i:i + 2] for i in range(len(word) - 1))
    return terms


class LexicalDenseReranker:
    """Blend BM25 keyword coverage with dense rank; keep cosine scores intact.

    This cannot add chunks or broaden access: it only reorders scoped candidates.
    Chinese bigrams avoid requiring a language-specific tokenizer dependency.
    """
    def rerank(self, question: str, candidates: Sequence[RankedSourceChunk]) -> Sequence[RankedSourceChunk]:
        if not candidates:
            return ()
        queries = set(_terms(question))
        documents = [Counter(_terms(item.source.content)) for item in candidates]
        lengths = [sum(document.values()) for document in documents]
        average = sum(lengths) / len(lengths) or 1
        frequencies = {term: sum(term in document for document in documents) for term in queries}
        lexical = []
        for document, length in zip(documents, lengths):
            score = 0.0
            for term in queries:
                frequency = document[term]
                if not frequency:
                    continue
                idf = log(1 + (len(documents) - frequencies[term] + .5) / (frequencies[term] + .5))
                score += idf * frequency * 2.2 / (frequency + 1.2 * (.25 + .75 * length / average))
            lexical.append(score)
        maximum = max(lexical)
        if maximum == 0:
            return tuple(candidates)
        scores = [.7 * score / maximum + .3 / (rank + 1) for rank, score in enumerate(lexical)]
        return tuple(candidates[i] for i in sorted(range(len(candidates)), key=lambda i: (-scores[i], i)))
