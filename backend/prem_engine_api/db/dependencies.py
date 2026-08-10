"""Lazy FastAPI database-session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from prem_engine_api.db.session import create_engine, create_session_factory

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine()
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Open one request-scoped session without connecting at application import."""

    async with _factory()() as session:
        yield session
