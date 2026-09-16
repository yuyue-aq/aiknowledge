from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from app.domain.documents import ParsedDocument
from app.services.chunking import TextChunker


class DocumentIngestionError(ValueError):
    """Raised when parsed content cannot safely become vector chunks."""


class DocumentEmbeddingPort(Protocol):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class PreparedChunk:
    ordinal: int
    content: str
    heading_path: tuple[str, ...]
    page_number: int | None
    embedding: list[float]


@dataclass(frozen=True, slots=True)
class PreparedDocument:
    chunks: tuple[PreparedChunk, ...]

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


class DocumentIngestionService:
    """Turn an already-parsed document into persistable vector chunks."""

    def __init__(
        self,
        *,
        embedding_client: DocumentEmbeddingPort,
        chunker: TextChunker,
        expected_embedding_dimension: int,
    ) -> None:
        if expected_embedding_dimension <= 0:
            raise ValueError("expected_embedding_dimension must be positive")
        self._embedding_client = embedding_client
        self._chunker = chunker
        self._expected_embedding_dimension = expected_embedding_dimension

    async def prepare(self, document: ParsedDocument) -> PreparedDocument:
        pending_chunks: list[tuple[str, tuple[str, ...], int | None]] = []
        for block in document.blocks:
            for chunk in self._chunker.split(block.text):
                pending_chunks.append((chunk.content, block.heading_path, block.page_number))
        if not pending_chunks:
            raise DocumentIngestionError("The parsed document has no indexable text.")

        vectors = await self._embedding_client.embed_documents(
            [content for content, _, _ in pending_chunks]
        )
        if len(vectors) != len(pending_chunks):
            raise DocumentIngestionError("Embedding response count does not match chunk count.")

        prepared_chunks: list[PreparedChunk] = []
        for ordinal, ((content, heading_path, page_number), vector) in enumerate(
            zip(pending_chunks, vectors), 1
        ):
            embedding = [float(value) for value in vector]
            if len(embedding) != self._expected_embedding_dimension:
                raise DocumentIngestionError(
                    "Embedding dimension mismatch: "
                    f"expected {self._expected_embedding_dimension}, "
                    f"received {len(embedding)}."
                )
            prepared_chunks.append(
                PreparedChunk(
                    ordinal=ordinal,
                    content=content,
                    heading_path=heading_path,
                    page_number=page_number,
                    embedding=embedding,
                )
            )

        return PreparedDocument(chunks=tuple(prepared_chunks))
