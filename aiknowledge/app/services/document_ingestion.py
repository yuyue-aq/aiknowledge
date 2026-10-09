from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
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
    source_block_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    content_hash: str | None = None
    token_count: int | None = None


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

    async def prepare(self, document: ParsedDocument, *, chunk_config: dict[str,object]|None=None) -> PreparedDocument:
        if chunk_config is not None:
            from app.services.chunk_plan import ChunkConfig,plan_chunks
            try:
                config=ChunkConfig.from_dict(chunk_config)
                budget=await self._embedding_client.document_token_budget()
                import asyncio
                planned=await asyncio.to_thread(plan_chunks,document,budget,config)
            except (ValueError,AttributeError) as exc:
                raise DocumentIngestionError('分块配置或模型容量无效。') from exc
            vectors=await self._embedding_client.embed_documents([x.content for x in planned])
            if len(vectors)!=len(planned):raise DocumentIngestionError('Embedding response count does not match chunk count.')
            result=[]
            for chunk,vector in zip(planned,vectors):
                values=[float(x) for x in vector]
                if len(values)!=self._expected_embedding_dimension or not all(math.isfinite(x) for x in values) or math.hypot(*values)==0:
                    raise DocumentIngestionError('Embedding must have valid dimensions and finite non-zero values.')
                result.append(PreparedChunk(chunk.ordinal,chunk.content,chunk.heading_path,chunk.page_number,values,
                    chunk.source_block_id,chunk.char_start,chunk.char_end,chunk.content_hash,chunk.token_count))
            return PreparedDocument(tuple(result))
        pending_chunks = []
        for block in document.blocks:
            splitter = getattr(self._embedding_client, 'split_document_text', None)
            chunks = await splitter(block.text) if splitter is not None else self._chunker.split(block.text)
            for chunk in chunks:
                pending_chunks.append((chunk, block))
        if not pending_chunks:
            raise DocumentIngestionError("The parsed document has no indexable text.")

        vectors = await self._embedding_client.embed_documents(
            [chunk.content for chunk, _ in pending_chunks]
        )
        if len(vectors) != len(pending_chunks):
            raise DocumentIngestionError("Embedding response count does not match chunk count.")

        prepared_chunks: list[PreparedChunk] = []
        for ordinal, ((chunk, block), vector) in enumerate(
            zip(pending_chunks, vectors), 1
        ):
            embedding = [float(value) for value in vector]
            if len(embedding) != self._expected_embedding_dimension:
                raise DocumentIngestionError(
                    "Embedding dimension mismatch: "
                    f"expected {self._expected_embedding_dimension}, "
                    f"received {len(embedding)}."
                )
            if not all(math.isfinite(x) for x in embedding) or math.hypot(*embedding) == 0:
                raise DocumentIngestionError('Embedding must contain finite non-zero values.')
            prepared_chunks.append(
                PreparedChunk(
                    ordinal=ordinal,
                    content=chunk.content,
                    heading_path=block.heading_path,
                    page_number=block.page_number,
                    embedding=embedding,
                    source_block_id=f'block-{block.ordinal}',
                    char_start=getattr(chunk, 'char_start', None),
                    char_end=getattr(chunk, 'char_end', None),
                    content_hash=sha256(chunk.content.encode('utf-8')).hexdigest(),
                    token_count=getattr(chunk, 'token_count', None),
                )
            )

        return PreparedDocument(chunks=tuple(prepared_chunks))
