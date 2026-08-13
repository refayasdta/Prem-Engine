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
    connect_args: dict[str, str] = {}
    if resolved.database_ssl_required:
        connect_args["ssl"] = "require"
    return create_async_engine(
        resolved.database_url,
        pool_pre_ping=True,
        pool_size=resolved.database_pool_size,
        max_overflow=resolved.database_max_overflow,
        pool_recycle=resolved.database_pool_recycle_seconds,
        pool_timeout=resolved.database_pool_timeout_seconds,
        connect_args=connect_args,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create sessions that preserve loaded state after commits."""

    return async_sessionmaker(engine, expire_on_commit=False)
