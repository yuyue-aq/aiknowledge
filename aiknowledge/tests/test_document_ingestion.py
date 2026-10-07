from __future__ import annotations

import pytest

from app.domain.documents import DocumentBlock, DocumentFormat, ParsedDocument
from app.services.document_ingestion import (
    DocumentIngestionError,
    DocumentIngestionService,
)
from app.services.chunking import TextChunker
from app.services.token_budget import TokenBudget


async def test_ingestion_uses_token_safe_source_spans_and_rejects_invalid_vectors():
    class Encoder(FakeEmbeddingClient):
        async def split_document_text(self, text):
            def tokenizer(value, **kwargs):
                return {'input_ids': [0] * (len(value) + 2)}
            return TokenBudget(tokenizer, capacity=8).split(text)
    source = '项目说明。\n最后的关键证据'
    document = ParsedDocument(filename='说明.txt', format=DocumentFormat.TEXT,
        blocks=(DocumentBlock(text=source, heading_path=(), ordinal=2, page_number=3),))
    service = DocumentIngestionService(embedding_client=Encoder(), chunker=TextChunker(), expected_embedding_dimension=3)
    result = await service.prepare(document)
    assert ''.join(x.content for x in result.chunks) == source
    assert all(x.source_block_id == 'block-2' for x in result.chunks)
    assert all(source[x.char_start:x.char_end] == x.content for x in result.chunks)
    assert all(x.token_count <= 8 and len(x.content_hash) == 64 for x in result.chunks)


@pytest.mark.parametrize('bad', [[0., 0., 0.], [float('nan'), 1., 0.]])
async def test_ingestion_never_persists_invalid_numeric_embedding(bad):
    class BadEncoder:
        async def embed_documents(self, texts):
            return [bad for _ in texts]
    document = ParsedDocument(filename='说明.txt', format=DocumentFormat.TEXT,
        blocks=(DocumentBlock(text='资料', heading_path=(), ordinal=1),))
    with pytest.raises(DocumentIngestionError):
        await DocumentIngestionService(embedding_client=BadEncoder(), chunker=TextChunker(), expected_embedding_dimension=3).prepare(document)


class FakeEmbeddingClient:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(index), 1.0, 2.0] for index, _ in enumerate(texts, 1)]


@pytest.mark.asyncio
async def test_ingestion_service_keeps_document_structure_with_chunk_vectors() -> None:
    document = ParsedDocument(
        filename="产品说明.md",
        format=DocumentFormat.MARKDOWN,
        blocks=(
            DocumentBlock(
                text="私密空间只允许拥有者访问。公开分类可单独开放。",
                heading_path=("访问边界",),
                ordinal=1,
            ),
        ),
    )
    service = DocumentIngestionService(
        embedding_client=FakeEmbeddingClient(),
        chunker=TextChunker(max_characters=16, overlap_characters=3),
        expected_embedding_dimension=3,
    )

    result = await service.prepare(document)

    assert result.chunk_count == 2
    assert result.chunks[0].heading_path == ("访问边界",)
    assert result.chunks[0].embedding == [1.0, 1.0, 2.0]
    assert result.chunks[1].ordinal == 2


@pytest.mark.asyncio
async def test_ingestion_service_fails_closed_when_embedding_dimensions_do_not_match() -> None:
    document = ParsedDocument(
        filename="资料.txt",
        format=DocumentFormat.TEXT,
        blocks=(DocumentBlock(text="可检索内容", heading_path=(), ordinal=1),),
    )
    service = DocumentIngestionService(
        embedding_client=FakeEmbeddingClient(),
        chunker=TextChunker(max_characters=32, overlap_characters=0),
        expected_embedding_dimension=4,
    )

    with pytest.raises(DocumentIngestionError, match="expected 4"):
        await service.prepare(document)
