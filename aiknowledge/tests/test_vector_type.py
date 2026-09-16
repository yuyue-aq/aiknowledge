from __future__ import annotations

from pgvector import Vector as PgVector
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg

from app.infrastructure.database.models import AsyncpgVector, ChunkRecord


def test_asyncpg_vector_keeps_a_pgvector_value_for_the_binary_codec() -> None:
    processor = AsyncpgVector(3).bind_processor(PGDialect_asyncpg())

    assert processor is not None
    value = processor([1.0, 2.0, 3.0])

    assert isinstance(value, PgVector)
    assert value.to_list() == [1.0, 2.0, 3.0]


def test_asyncpg_vector_preserves_text_binding_for_other_postgres_drivers() -> None:
    processor = AsyncpgVector(3).bind_processor(postgresql.dialect())

    assert processor is not None
    assert processor([1.0, 2.0, 3.0]) == "[1.0,2.0,3.0]"


def test_chunk_embedding_uses_the_asyncpg_compatibility_type() -> None:
    assert isinstance(ChunkRecord.__table__.c.embedding.type, AsyncpgVector)
    assert ChunkRecord.__table__.c.embedding.type.dim == 1024
