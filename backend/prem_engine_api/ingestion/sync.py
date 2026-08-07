"""Audited provider fetch followed by transactional normalization."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prem_engine_api.ingestion.fixtures import FixtureIngestionSummary, FixtureIngestor
from prem_engine_api.providers.kickoffapi.client import KickoffApiClient


@dataclass(frozen=True)
class FixtureSyncOutcome:
    provider_request_uuid: UUID
    raw_fetch_uuid: UUID
    ingestion: FixtureIngestionSummary


async def sync_fixtures(
    *,
    client: KickoffApiClient,
    session_factory: async_sessionmaker[AsyncSession],
    league: str,
    season: int,
    limit: int = 50,
) -> FixtureSyncOutcome:
    """Capture a fixture page before normalizing it in a separate transaction."""

    captured = await client.get(
        "/api/v2/fixtures",
        params={"league": league, "season": season, "limit": limit},
    )
    async with session_factory() as session, session.begin():
        summary = await FixtureIngestor(session).ingest(captured.payload)
    return FixtureSyncOutcome(
        provider_request_uuid=captured.provider_request_uuid,
        raw_fetch_uuid=captured.raw_fetch_uuid,
        ingestion=summary,
    )
