"""Async database engine and session factory construction."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from prem_engine_api.config import Settings, get_settings


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create an async engine without logging credentials or SQL values."""

    resolved = settings or get_settings()
    return create_async_engine(resolved.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create sessions that preserve loaded state after commits."""

    return async_sessionmaker(engine, expire_on_commit=False)
