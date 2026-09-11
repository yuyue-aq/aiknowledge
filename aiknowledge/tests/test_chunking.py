from __future__ import annotations

import pytest

from app.services.chunking import TextChunker


def test_text_chunker_prefers_paragraph_and_sentence_boundaries() -> None:
    chunker = TextChunker(max_characters=18, overlap_characters=4)

    chunks = chunker.split("第一段很短。\n\n第二段也很短。第三段继续说明。")

    assert [chunk.ordinal for chunk in chunks] == list(range(1, len(chunks) + 1))
    assert all(chunk.content for chunk in chunks)
    assert all(len(chunk.content) <= 18 for chunk in chunks)
    assert "第一段很短。" in chunks[0].content
    assert "第三段继续说明。" in chunks[-1].content


def test_text_chunker_rejects_an_invalid_overlap() -> None:
    with pytest.raises(ValueError, match="overlap"):
        TextChunker(max_characters=10, overlap_characters=10)
