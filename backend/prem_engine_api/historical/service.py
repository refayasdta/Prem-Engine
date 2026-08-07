"""Idempotent normalization of historical Premier League season files."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.enums import FixtureStatus, KickoffPrecision, ResultKind
from prem_engine_api.domain.models import (
    ActualResultRevision,
    Competition,
    FixtureScheduleRevision,
    HistoricalMatchRecord,
    HistoricalSourceFile,
    Match,
    MatchExternalReference,
    Season,
    SeasonClub,
)
from prem_engine_api.historical.contracts import (
    HistoricalDataError,
    HistoricalMatchRow,
    parse_historical_csv,
)
from prem_engine_api.historical.mapping import (
    normalize_club_alias,
    resolve_club,
    seed_reviewed_aliases,
)
from prem_engine_api.providers.raw_storage import LocalRawResponseStore

FOOTBALL_DATA_PROVIDER = "football-data.co.uk"
PREMIER_LEAGUE_CODE = "E0"
LONDON = ZoneInfo("Europe/London")


@dataclass(frozen=True)
class HistoricalImportSummary:
    source_file_uuid: str
    season_label: str
    source_checksum: str
    source_rows: int
    matches_created: int
    results_created: int
    corrections_created: int
    reused_existing_source: bool


def season_label(start_year: int) -> str:
    return f"{start_year}/{(start_year + 1) % 100:02d}"


def _kickoff(row: HistoricalMatchRow) -> tuple[datetime, KickoffPrecision]:
    if row.match_time is None:
        local = datetime.combine(row.match_date, time(12, 0), tzinfo=LONDON)
        return local.astimezone(UTC), KickoffPrecision.DATE_ONLY
    local = datetime.combine(row.match_date, row.match_time, tzinfo=LONDON)
    return local.astimezone(UTC), KickoffPrecision.EXACT


def _available_after(kickoff_at: datetime, precision: KickoffPrecision) -> datetime:
    if precision is KickoffPrecision.DATE_ONLY:
        return kickoff_at + timedelta(hours=12)
    return kickoff_at + timedelta(hours=4)


async def _competition_and_season(
    session: AsyncSession, start_year: int
) -> tuple[Competition, Season]:
    competition = await session.scalar(
        select(Competition).where(Competition.slug == "premier-league")
    )
    if competition is None:
        competition = Competition(
            slug="premier-league",
            name="Premier League",
            country_code="GB",
            rules_version="premier-league-v1",
        )
        session.add(competition)
        await session.flush()

    label = season_label(start_year)
    season = await session.scalar(
        select(Season).where(
            Season.competition_uuid == competition.competition_uuid,
            Season.label == label,
        )
    )
    if season is None:
        season = Season(
            competition_uuid=competition.competition_uuid,
            label=label,
            start_date=date(start_year, 7, 1),
            end_date=date(start_year + 1, 6, 30),
        )
        session.add(season)
        await session.flush()
    return competition, season


def _external_fixture_id(
    *, season: Season, row: HistoricalMatchRow, home_alias: str, away_alias: str
) -> str:
    return f"E0:{season.label}:{row.match_date.isoformat()}:{home_alias}:{away_alias}"


async def _schedule_revision(
    session: AsyncSession,
    *,
    match: Match,
    kickoff_at: datetime,
    observed_at: datetime,
) -> None:
    latest = await session.scalar(
        select(FixtureScheduleRevision)
        .where(FixtureScheduleRevision.match_uuid == match.match_uuid)
        .order_by(FixtureScheduleRevision.revision_number.desc())
        .limit(1)
    )
    if latest is not None and latest.kickoff_at == kickoff_at:
        return
    if latest is not None:
        latest.superseded_at = observed_at
    revision_number = 1 if latest is None else latest.revision_number + 1
    session.add(
        FixtureScheduleRevision(
            match_uuid=match.match_uuid,
            revision_number=revision_number,
            kickoff_at=kickoff_at,
            canonical_status=FixtureStatus.FINISHED,
            provider_status="historical_finished",
            observed_at=observed_at,
        )
    )


async def _match_for_row(
    session: AsyncSession,
    *,
    season: Season,
    row: HistoricalMatchRow,
    home_club_uuid: UUID,
    away_club_uuid: UUID,
    home_alias: str,
    away_alias: str,
    observed_at: datetime,
) -> tuple[Match, bool]:
    external_id = _external_fixture_id(
        season=season,
        row=row,
        home_alias=home_alias,
        away_alias=away_alias,
    )
    reference = await session.scalar(
        select(MatchExternalReference).where(
            MatchExternalReference.provider == FOOTBALL_DATA_PROVIDER,
            MatchExternalReference.external_fixture_id == external_id,
        )
    )
    if reference is not None:
        match = await session.get(Match, reference.match_uuid)
        if match is None:
            raise HistoricalDataError("historical match reference points to a missing match")
        if (
            match.season_uuid != season.season_uuid
            or match.home_club_uuid != home_club_uuid
            or match.away_club_uuid != away_club_uuid
        ):
            raise HistoricalDataError(f"stable fixture identity conflicts for {external_id}")
        revised_kickoff, revised_precision = _kickoff(row)
        if match.current_kickoff_at != revised_kickoff:
            match.current_kickoff_at = revised_kickoff
            match.prediction_due_at = revised_kickoff - timedelta(hours=24)
            match.kickoff_precision = revised_precision
            await _schedule_revision(
                session,
                match=match,
                kickoff_at=revised_kickoff,
                observed_at=observed_at,
            )
        match.status = FixtureStatus.FINISHED
        return match, False

    kickoff_at, precision = _kickoff(row)
    day_start = datetime.combine(row.match_date, time.min, tzinfo=LONDON).astimezone(UTC)
    day_end = day_start + timedelta(days=1)
    candidates = list(
        await session.scalars(
            select(Match).where(
                Match.season_uuid == season.season_uuid,
                Match.home_club_uuid == home_club_uuid,
                Match.away_club_uuid == away_club_uuid,
                Match.current_kickoff_at >= day_start,
                Match.current_kickoff_at < day_end,
            )
        )
    )
    if len(candidates) > 1:
        raise HistoricalDataError(f"ambiguous canonical fixture identity for {external_id}")
    created = not candidates
    if candidates:
        match = candidates[0]
    else:
        match = Match(
            season_uuid=season.season_uuid,
            home_club_uuid=home_club_uuid,
            away_club_uuid=away_club_uuid,
            status=FixtureStatus.FINISHED,
            current_kickoff_at=kickoff_at,
            kickoff_precision=precision,
            prediction_due_at=kickoff_at - timedelta(hours=24),
        )
        session.add(match)
        await session.flush()
        await _schedule_revision(
            session,
            match=match,
            kickoff_at=kickoff_at,
            observed_at=observed_at,
        )
    session.add(
        MatchExternalReference(
            match_uuid=match.match_uuid,
            provider=FOOTBALL_DATA_PROVIDER,
            external_fixture_id=external_id,
            observed_from=observed_at,
        )
    )
    return match, created


async def _result_for_row(
    session: AsyncSession,
    *,
    match: Match,
    row: HistoricalMatchRow,
    object_key: str,
    observed_at: datetime,
) -> tuple[bool, bool]:
    current = await session.scalar(
        select(ActualResultRevision).where(
            ActualResultRevision.match_uuid == match.match_uuid,
            ActualResultRevision.accepted.is_(True),
        )
    )
    if (
        current is not None
        and current.home_goals == row.full_time_home_goals
        and current.away_goals == row.full_time_away_goals
    ):
        return False, False
    latest_revision = await session.scalar(
        select(func.max(ActualResultRevision.revision_number)).where(
            ActualResultRevision.match_uuid == match.match_uuid
        )
    )
    correction = current is not None
    if current is not None:
        current.accepted = False
    session.add(
        ActualResultRevision(
            match_uuid=match.match_uuid,
            revision_number=(latest_revision or 0) + 1,
            home_goals=row.full_time_home_goals,
            away_goals=row.full_time_away_goals,
            result_kind=ResultKind.REGULAR,
            accepted=True,
            provider_payload_key=object_key,
            observed_at=observed_at,
        )
    )
    return True, correction


async def import_historical_csv(
    session: AsyncSession,
    *,
    body: bytes,
    source_url: str,
    retrieved_at: datetime,
    season_start_year: int,
    alias_registry_path: Path,
    raw_store: LocalRawResponseStore,
) -> HistoricalImportSummary:
    """Archive and atomically normalize one season; exact re-imports are no-ops."""

    checksum = hashlib.sha256(body).hexdigest()
    existing = await session.scalar(
        select(HistoricalSourceFile).where(
            HistoricalSourceFile.provider == FOOTBALL_DATA_PROVIDER,
            HistoricalSourceFile.source_url == source_url,
            HistoricalSourceFile.response_checksum == checksum,
        )
    )
    if existing is not None:
        return HistoricalImportSummary(
            source_file_uuid=str(existing.source_file_uuid),
            season_label=existing.season_label,
            source_checksum=existing.response_checksum,
            source_rows=existing.row_count,
            matches_created=0,
            results_created=0,
            corrections_created=0,
            reused_existing_source=True,
        )

    stored = raw_store.store(
        provider=FOOTBALL_DATA_PROVIDER,
        body=body,
        fetched_at=retrieved_at,
        extension="csv",
    )
    parsed = parse_historical_csv(body)
    if any(row.division not in (None, PREMIER_LEAGUE_CODE) for row in parsed.rows):
        raise HistoricalDataError("source file contains a non-Premier-League division")
    _, season = await _competition_and_season(session, season_start_year)
    if any(
        row.match_date < season.start_date or row.match_date > season.end_date
        for row in parsed.rows
    ):
        raise HistoricalDataError("source file contains a match outside the requested season")
    source_file = HistoricalSourceFile(
        provider=FOOTBALL_DATA_PROVIDER,
        competition_code=PREMIER_LEAGUE_CODE,
        season_label=season.label,
        source_url=source_url,
        retrieved_at=retrieved_at,
        response_checksum=stored.checksum,
        object_key=stored.object_key,
        schema_fingerprint=parsed.schema_fingerprint,
        row_count=len(parsed.rows),
    )
    session.add(source_file)
    await session.flush()
    aliases = await seed_reviewed_aliases(
        session,
        provider=FOOTBALL_DATA_PROVIDER,
        registry_path=alias_registry_path,
        reviewed_at=retrieved_at,
    )

    seen_fixture_ids: set[str] = set()
    matches_created = 0
    results_created = 0
    corrections_created = 0
    for row in parsed.rows:
        home = resolve_club(aliases, row.home_team)
        away = resolve_club(aliases, row.away_team)
        home_alias = normalize_club_alias(row.home_team)
        away_alias = normalize_club_alias(row.away_team)
        fixture_id = _external_fixture_id(
            season=season,
            row=row,
            home_alias=home_alias,
            away_alias=away_alias,
        )
        if fixture_id in seen_fixture_ids:
            raise HistoricalDataError(f"duplicate fixture row: {fixture_id}")
        seen_fixture_ids.add(fixture_id)

        for club in (home, away):
            membership = await session.scalar(
                select(SeasonClub).where(
                    SeasonClub.season_uuid == season.season_uuid,
                    SeasonClub.club_uuid == club.club_uuid,
                )
            )
            if membership is None:
                session.add(SeasonClub(season_uuid=season.season_uuid, club_uuid=club.club_uuid))
                await session.flush()

        match, created = await _match_for_row(
            session,
            season=season,
            row=row,
            home_club_uuid=home.club_uuid,
            away_club_uuid=away.club_uuid,
            home_alias=home_alias,
            away_alias=away_alias,
            observed_at=retrieved_at,
        )
        matches_created += int(created)
        result_created, correction = await _result_for_row(
            session,
            match=match,
            row=row,
            object_key=stored.object_key,
            observed_at=retrieved_at,
        )
        results_created += int(result_created)
        corrections_created += int(correction)
        kickoff_at, precision = _kickoff(row)
        session.add(
            HistoricalMatchRecord(
                source_file_uuid=source_file.source_file_uuid,
                match_uuid=match.match_uuid,
                source_row_number=row.source_row_number,
                row_checksum=row.row_checksum,
                available_after=_available_after(kickoff_at, precision),
                half_time_home_goals=row.half_time_home_goals,
                half_time_away_goals=row.half_time_away_goals,
                referee=row.referee,
                statistics=row.statistics,
                benchmark_odds=row.benchmark_odds,
                odds_timing="mixed_or_unknown",
                odds_training_eligible=False,
            )
        )
    await session.flush()
    return HistoricalImportSummary(
        source_file_uuid=str(source_file.source_file_uuid),
        season_label=season.label,
        source_checksum=stored.checksum,
        source_rows=len(parsed.rows),
        matches_created=matches_created,
        results_created=results_created,
        corrections_created=corrections_created,
        reused_existing_source=False,
    )
