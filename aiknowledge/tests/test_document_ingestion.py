from __future__ import annotations

import pytest

from app.domain.documents import DocumentBlock, DocumentFormat, ParsedDocument
from app.services.document_ingestion import (
    DocumentIngestionError,
    DocumentIngestionService,
)
from app.services.chunking import TextChunker


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
