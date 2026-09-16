from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import Database


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Own one transaction per API request without holding it during streams."""

    database: Database = request.app.state.database
    async with database.session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
