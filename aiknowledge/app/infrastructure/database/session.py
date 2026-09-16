from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pgvector.asyncpg import register_vector
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


class DatabaseUnavailable(RuntimeError):
    """A sanitized database availability failure."""


class Database:
    """Own the async SQLAlchemy engine and register pgvector codecs per connection."""

    def __init__(self, *, url: str, pool_size: int = 5, max_overflow: int = 10) -> None:
        parsed_url = make_url(url)
        if parsed_url.drivername != "postgresql+asyncpg":
            raise ValueError("Database URL must use the postgresql+asyncpg driver.")
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        self._session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        @event.listens_for(self.engine.sync_engine, "connect")
        def register_pgvector(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            # SQLAlchemy's AdaptedConnection exposes run_async precisely for
            # asyncpg-only initialization such as pgvector codec registration.
            dbapi_connection.run_async(register_vector)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            yield session

    async def ping(self) -> None:
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise DatabaseUnavailable("Database is unavailable.") from exc

    async def dispose(self) -> None:
        await self.engine.dispose()
