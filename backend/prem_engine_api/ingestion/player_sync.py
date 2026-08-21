"""Bounded current player-context synchronization plan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prem_engine_api.domain.enums import FixtureStatus
from prem_engine_api.domain.models import (
    ClubExternalReference,
    Match,
    MatchExternalReference,
    PlayerMatchPerformance,
    SquadMembership,
)
from prem_engine_api.ingestion.current_fpl import ingest_current_fpl_squads
from prem_engine_api.ingestion.player_context import (
    PlayerContextIngestionSummary,
    PlayerContextIngestor,
)
from prem_engine_api.providers.current_fpl.client import CurrentFplClient
from prem_engine_api.providers.kickoffapi.client import (
    CapturedProviderResponse,
    KickoffApiClient,
)

PROVIDER = "kickoffapi"


@dataclass(frozen=True)
class PlayerContextSyncOutcome:
    requests_used: int
    requests_failed: int
    squads_requested: int
    matches_requested: int
    fpl_fallback_used: bool
    summaries: tuple[PlayerContextIngestionSummary, ...]


def _next_cursor(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    value = meta.get("nextCursor") or meta.get("next_cursor")
    return str(value) if value not in (None, "") else None


async def _club_targets(
    session: AsyncSession, *, season_uuid: UUID, limit: int, now: datetime
) -> tuple[tuple[UUID, str], ...]:
    match_clubs = list(
        (
            await session.execute(
                select(Match.home_club_uuid, Match.away_club_uuid).where(
                    Match.season_uuid == season_uuid
                )
            )
        ).all()
    )
    club_ids = {club_uuid for pair in match_clubs for club_uuid in pair}
    if not club_ids:
        return ()
    references = list(
        (
            await session.execute(
                select(
                    ClubExternalReference.club_uuid,
                    ClubExternalReference.external_club_id,
                ).where(
                    ClubExternalReference.provider == PROVIDER,
                    ClubExternalReference.club_uuid.in_(club_ids),
                )
            )
        ).all()
    )
    freshness: list[tuple[bool, datetime | None, datetime | None, UUID, str]] = []
    for club_uuid, external_id in references:
        player_count = int(
            await session.scalar(
                select(func.count())
                .select_from(SquadMembership)
                .where(
                    SquadMembership.season_uuid == season_uuid,
                    SquadMembership.club_uuid == club_uuid,
                    SquadMembership.left_on.is_(None),
                )
            )
            or 0
        )
        goalkeeper_count = int(
            await session.scalar(
                select(func.count())
                .select_from(SquadMembership)
                .where(
                    SquadMembership.season_uuid == season_uuid,
                    SquadMembership.club_uuid == club_uuid,
                    SquadMembership.left_on.is_(None),
                    func.lower(SquadMembership.primary_position).in_(("goalkeeper", "gk")),
                )
            )
            or 0
        )
        adequate = player_count >= 15 and goalkeeper_count >= 1
        latest = await session.scalar(
            select(func.max(SquadMembership.updated_at)).where(
                SquadMembership.season_uuid == season_uuid,
                SquadMembership.club_uuid == club_uuid,
            )
        )
        next_kickoff = await session.scalar(
            select(func.min(Match.current_kickoff_at)).where(
                Match.season_uuid == season_uuid,
                Match.current_kickoff_at >= now,
                Match.status.in_((FixtureStatus.SCHEDULED, FixtureStatus.POSTPONED)),
                (Match.home_club_uuid == club_uuid) | (Match.away_club_uuid == club_uuid),
            )
        )
        freshness.append((adequate, latest, next_kickoff, club_uuid, external_id))
    freshness.sort(
        key=lambda item: (
            item[0],
            item[2] is None,
            item[2] or datetime.max.replace(tzinfo=UTC),
            item[1] is not None,
            item[1] or datetime.min.replace(tzinfo=UTC),
            str(item[3]),
        )
    )
    return tuple((club_uuid, external_id) for _, _, _, club_uuid, external_id in freshness[:limit])


async def _match_targets(
    session: AsyncSession, *, season_uuid: UUID, limit: int
) -> tuple[tuple[UUID, str], ...]:
    candidates = list(
        (
            await session.execute(
                select(Match.match_uuid, MatchExternalReference.external_fixture_id)
                .join(
                    MatchExternalReference,
                    MatchExternalReference.match_uuid == Match.match_uuid,
                )
                .where(
                    Match.season_uuid == season_uuid,
                    Match.status.in_(
                        (FixtureStatus.FINISHED, FixtureStatus.ABANDONED, FixtureStatus.AWARDED)
                    ),
                    MatchExternalReference.provider == PROVIDER,
                )
                .order_by(Match.current_kickoff_at.desc())
            )
        ).all()
    )
    selected: list[tuple[UUID, str]] = []
    for match_uuid, external_id in candidates:
        count = int(
            await session.scalar(
                select(func.count())
                .select_from(PlayerMatchPerformance)
                .where(PlayerMatchPerformance.match_uuid == match_uuid)
            )
            or 0
        )
        if count == 0:
            selected.append((match_uuid, external_id))
        if len(selected) == limit:
            break
    return tuple(selected)


async def sync_player_context(
    *,
    client: KickoffApiClient,
    fpl_client: CurrentFplClient | None = None,
    session_factory: async_sessionmaker[AsyncSession],
    season_uuid: UUID,
    league: str,
    season: int,
    max_requests: int = 16,
    max_squads: int = 10,
    max_matches: int = 2,
) -> PlayerContextSyncOutcome:
    """Use a deterministic request budget: global context, stale squads, then match details."""

    if max_requests < 1 or max_squads < 0 or max_matches < 0:
        raise ValueError("sync request and target limits must be non-negative")
    async with session_factory() as session:
        club_targets = await _club_targets(
            session,
            season_uuid=season_uuid,
            limit=min(max_squads, max_requests),
            now=datetime.now(UTC),
        )
        match_targets = await _match_targets(session, season_uuid=season_uuid, limit=max_matches)

    used = failed = squads_requested = matches_requested = 0
    summaries: list[PlayerContextIngestionSummary] = []
    fallback_targets: set[UUID] = set()

    async def capture(
        endpoint: str, params: dict[str, str | int | float | bool]
    ) -> CapturedProviderResponse | None:
        nonlocal used, failed
        if used >= max_requests:
            return None
        used += 1
        try:
            return await client.get(endpoint, params=params)
        except httpx.HTTPStatusError:
            failed += 1
            return None

    for endpoint, method, page_limit in (
        ("/api/v2/injuries", "ingest_injuries", 3),
        ("/api/v2/transfers", "ingest_transfers", 2),
    ):
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(page_limit):
            params: dict[str, str | int | float | bool] = {
                "league": league,
                "season": season,
                "limit": 50,
            }
            if cursor is not None:
                params["cursor"] = cursor
            captured = await capture(endpoint, params)
            if captured is None:
                break
            observed_at = datetime.now(UTC)
            async with session_factory.begin() as session:
                ingestor = PlayerContextIngestor(session)
                ingest = getattr(ingestor, method)
                summaries.append(
                    await ingest(
                        captured.payload,
                        observed_at=observed_at,
                        provider_payload_key=f"kickoffapi:{captured.raw_fetch_uuid}",
                    )
                )
            next_cursor = _next_cursor(captured.payload)
            if next_cursor is None:
                break
            if next_cursor in seen_cursors:
                raise RuntimeError(f"KickoffAPI repeated {endpoint} cursor {next_cursor!r}")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    match_request_reserve = min(len(match_targets) * 2, max_requests - used)
    squad_request_budget = max(0, max_requests - used - match_request_reserve)
    for club_uuid, external_club_id in club_targets[:squad_request_budget]:
        captured = await capture(f"/api/v2/teams/{external_club_id}/squad", {})
        if captured is None:
            continue
        squads_requested += 1
        async with session_factory.begin() as session:
            summary = await PlayerContextIngestor(session).ingest_squad(
                captured.payload,
                season_uuid=season_uuid,
                club_uuid=club_uuid,
                observed_at=datetime.now(UTC),
            )
            summaries.append(summary)
            player_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(SquadMembership)
                    .where(
                        SquadMembership.season_uuid == season_uuid,
                        SquadMembership.club_uuid == club_uuid,
                        SquadMembership.left_on.is_(None),
                    )
                )
                or 0
            )
            goalkeeper_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(SquadMembership)
                    .where(
                        SquadMembership.season_uuid == season_uuid,
                        SquadMembership.club_uuid == club_uuid,
                        SquadMembership.left_on.is_(None),
                        func.lower(SquadMembership.primary_position).in_(("goalkeeper", "gk")),
                    )
                )
                or 0
            )
            if player_count < 15 or goalkeeper_count < 1:
                fallback_targets.add(club_uuid)

    fallback_used = False
    if fallback_targets and fpl_client is not None:
        captured = await fpl_client.get_bootstrap()
        async with session_factory.begin() as session:
            summaries.append(
                await ingest_current_fpl_squads(
                    session,
                    captured.payload,
                    season_uuid=season_uuid,
                    target_club_uuids=fallback_targets,
                    observed_at=datetime.now(UTC),
                )
            )
        fallback_used = True

    for match_uuid, external_fixture_id in match_targets:
        if used + 2 > max_requests:
            break
        match_had_request = False
        for suffix, method in (
            ("lineups", "ingest_lineups"),
            ("players", "ingest_performances"),
        ):
            captured = await capture(f"/api/v2/fixtures/{external_fixture_id}/{suffix}", {})
            match_had_request = True
            if captured is None:
                continue
            raw_fetch_uuid = captured.raw_fetch_uuid
            async with session_factory.begin() as session:
                ingestor = PlayerContextIngestor(session)
                ingest = getattr(ingestor, method)
                summaries.append(
                    await ingest(
                        captured.payload,
                        match_uuid=match_uuid,
                        observed_at=datetime.now(UTC),
                        provider_payload_key=f"kickoffapi:{raw_fetch_uuid}",
                    )
                )
        matches_requested += int(match_had_request)

    return PlayerContextSyncOutcome(
        requests_used=used,
        requests_failed=failed,
        squads_requested=squads_requested,
        matches_requested=matches_requested,
        fpl_fallback_used=fallback_used,
        summaries=tuple(summaries),
    )
