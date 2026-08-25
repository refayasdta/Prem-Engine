"""Bounded, audited fixture synchronization for one local installation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prem_engine_api.config import Settings
from prem_engine_api.ingestion.fixtures import FixtureIngestionSummary, FixtureIngestor
from prem_engine_api.providers.kickoffapi.client import KickoffApiClient
from prem_engine_api.providers.kickoffapi.contracts import FixtureEnvelope, ProviderFixture


@dataclass(frozen=True)
class FixtureSyncProgress:
    pages_processed: int = 0
    records_received: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_unchanged: int = 0
    records_pending_review: int = 0


@dataclass(frozen=True)
class LocalFixtureSyncOutcome:
    full_season: bool
    season: int
    progress: FixtureSyncProgress
    provider_request_uuids: tuple[UUID, ...]
    raw_fetch_uuids: tuple[UUID, ...]


ProgressCallback = Callable[[FixtureSyncProgress], Awaitable[None]]


def active_season_start_year(now: datetime, configured: int | None) -> int:
    """Return the configured season or infer the July-to-June Premier League season."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("season inference time must include a timezone")
    return configured if configured is not None else now.year - int(now.month < 7)


def next_cursor(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    value = meta.get("nextCursor") or meta.get("next_cursor")
    return str(value) if value not in (None, "") else None


def _add_progress(
    progress: FixtureSyncProgress, summary: FixtureIngestionSummary
) -> FixtureSyncProgress:
    return FixtureSyncProgress(
        pages_processed=progress.pages_processed + 1,
        records_received=progress.records_received + summary.received,
        records_created=progress.records_created + summary.created,
        records_updated=progress.records_updated + summary.updated,
        records_unchanged=progress.records_unchanged + summary.unchanged,
        records_pending_review=progress.records_pending_review + summary.pending_review,
    )


async def synchronize_local_fixtures(
    *,
    client: KickoffApiClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    now: datetime,
    full_season: bool,
    progress_callback: ProgressCallback | None = None,
) -> LocalFixtureSyncOutcome:
    """Reconcile a complete season or the bounded active fixture window."""

    season = active_season_start_year(now, settings.local_season_start_year)
    cursor: str | None = None
    seen_cursors: set[str] = set()
    progress = FixtureSyncProgress()
    provider_requests: list[UUID] = []
    raw_fetches: list[UUID] = []
    fixtures: list[ProviderFixture] = []
    completed = False

    for _ in range(settings.local_fixture_sync_max_pages):
        params: dict[str, str | int | float | bool] = {
            "league": settings.local_competition_code,
            "season": season,
            "limit": settings.local_fixture_sync_page_size,
        }
        if not full_season:
            params.update(
                {
                    "from": (now - timedelta(days=settings.local_fixture_sync_lookback_days))
                    .date()
                    .isoformat(),
                    "to": (now + timedelta(days=settings.local_fixture_sync_horizon_days))
                    .date()
                    .isoformat(),
                }
            )
        if cursor is not None:
            params["cursor"] = cursor

        captured = await client.get("/api/v2/fixtures", params=params)
        envelope = FixtureEnvelope.model_validate(captured.payload)
        fixtures.extend(envelope.data)
        provider_requests.append(captured.provider_request_uuid)
        raw_fetches.append(captured.raw_fetch_uuid)

        following = next_cursor(captured.payload)
        if following is None:
            completed = True
            break
        if following in seen_cursors:
            raise RuntimeError(f"KickoffAPI repeated fixture cursor {following!r}")
        seen_cursors.add(following)
        cursor = following

    if not completed:
        raise RuntimeError(
            "fixture synchronization exceeded the configured page limit before completion"
        )
    async with session_factory.begin() as session:
        summary = await FixtureIngestor(session).ingest(FixtureEnvelope(data=fixtures))
    progress = FixtureSyncProgress(
        pages_processed=len(provider_requests),
        records_received=summary.received,
        records_created=summary.created,
        records_updated=summary.updated,
        records_unchanged=summary.unchanged,
        records_pending_review=summary.pending_review,
    )
    if progress_callback is not None:
        await progress_callback(progress)
    return LocalFixtureSyncOutcome(
        full_season=full_season,
        season=season,
        progress=progress,
        provider_request_uuids=tuple(provider_requests),
        raw_fetch_uuids=tuple(raw_fetches),
    )
