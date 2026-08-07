"""Database fixtures used by integration tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from prem_engine_api.config import get_settings
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    database_url = (
        os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or get_settings().database_url
    )

    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
