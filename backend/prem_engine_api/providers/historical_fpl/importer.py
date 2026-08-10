"""Idempotent import of audited historical FPL player performances."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.models import (
    Club,
    HistoricalSourceFile,
    Match,
    MatchExternalReference,
    Player,
    PlayerExternalReference,
    PlayerMatchPerformance,
    Season,
)
from prem_engine_api.historical.mapping import resolve_club, seed_reviewed_aliases
from prem_engine_api.providers.historical_fpl.archive import ArchivedCsv, ArchivedSeason

PROVIDER = "historical-fpl"
POSITION_MAP = {
    "GK": "goalkeeper",
    "GKP": "goalkeeper",
    "DEF": "defender",
    "MID": "midfielder",
    "FWD": "attacker",
}
SAFE_STATISTICS = {
    "assists": "assists",
    "bonus": "bonus",
    "bps": "bps",
    "clean_sheets": "clean_sheets",
    "expected_assists": "expected_assists",
    "expected_goal_involvements": "expected_goal_involvements",
    "expected_goals": "expected_goals",
    "expected_goals_conceded": "expected_goals_conceded",
    "goals_conceded": "goals_conceded",
    "goals_scored": "goals",
    "own_goals": "own_goals",
    "penalties_missed": "penalties_missed",
    "penalties_saved": "penalties_saved",
    "red_cards": "red_cards",
    "saves": "saves",
    "total_points": "fpl_total_points",
    "yellow_cards": "yellow_cards",
}


class HistoricalFplImportError(ValueError):
    """Raised when a source identity or immutable observation conflicts."""


@dataclass(frozen=True)
class HistoricalFplImportSummary:
    seasons_imported: int
    source_files_registered: int
    fixture_references_created: int
    players_created: int
    player_references_created: int
    performances_created: int
    performances_reused: int
    observed_start_records: int
    unknown_start_records: int


def _schema_fingerprint(source: ArchivedCsv) -> str:
    return hashlib.sha256("\0".join(source.parsed.columns).encode()).hexdigest()


def _row_checksum(row: dict[str, str]) -> str:
    body = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode()).hexdigest()


def _integer(value: str, *, field: str, row_number: int) -> int:
    try:
        return int(float(value))
    except ValueError as error:
        raise HistoricalFplImportError(f"row {row_number}: invalid {field}") from error


def _number(value: str) -> int | float:
    parsed = float(value or 0)
    return int(parsed) if parsed.is_integer() else parsed


def _season_label(value: str) -> str:
    start, end = value.split("-", 1)
    return f"{start}/{end}"


async def _source_file(
    session: AsyncSession, *, season_label: str, source: ArchivedCsv
) -> tuple[HistoricalSourceFile, bool]:
    existing = await session.scalar(
        select(HistoricalSourceFile).where(
            HistoricalSourceFile.provider == PROVIDER,
            HistoricalSourceFile.source_url == source.source_url,
            HistoricalSourceFile.response_checksum == source.checksum,
        )
    )
    if existing is not None:
        if existing.object_key != source.object_key or existing.row_count != len(
            source.parsed.rows
        ):
            raise HistoricalFplImportError(
                "registered source metadata conflicts with local capture"
            )
        return existing, False
    record = HistoricalSourceFile(
        provider=PROVIDER,
        competition_code="EPL",
        season_label=season_label,
        source_url=source.source_url,
        retrieved_at=source.retrieved_at,
        response_checksum=source.checksum,
        object_key=source.object_key,
        schema_fingerprint=_schema_fingerprint(source),
        row_count=len(source.parsed.rows),
    )
    session.add(record)
    await session.flush()
    return record, True


def _canonical_name(row: dict[str, str]) -> str:
    parts = [row.get("first_name", "").strip(), row.get("second_name", "").strip()]
    name = " ".join(part for part in parts if part) or row.get("web_name", "").strip()
    if not name:
        raise HistoricalFplImportError("player registry contains a blank name")
    return name


def _fixture_teams(
    rows: tuple[dict[str, str], ...], clubs: dict[str, Club]
) -> dict[str, tuple[UUID, UUID, datetime]]:
    sides: dict[str, dict[bool, Club]] = {}
    kickoffs: dict[str, datetime] = {}
    for row in rows:
        fixture_id = row.get("fixture", "").strip()
        team_name = row.get("team", "").strip()
        if not fixture_id or not team_name:
            continue
        was_home = row.get("was_home", "").strip().casefold() == "true"
        club = resolve_club(clubs, team_name)
        existing = sides.setdefault(fixture_id, {}).get(was_home)
        if existing is not None and existing.club_uuid != club.club_uuid:
            raise HistoricalFplImportError(f"fixture {fixture_id} has conflicting team identities")
        sides[fixture_id][was_home] = club
        kickoff = datetime.fromisoformat(row["kickoff_time"].replace("Z", "+00:00"))
        if kickoff.tzinfo is None or kickoff.utcoffset() is None:
            raise HistoricalFplImportError(f"fixture {fixture_id} kickoff is timezone-naive")
        if fixture_id in kickoffs and kickoffs[fixture_id] != kickoff:
            raise HistoricalFplImportError(f"fixture {fixture_id} has conflicting kickoff times")
        kickoffs[fixture_id] = kickoff
    output: dict[str, tuple[UUID, UUID, datetime]] = {}
    for fixture_id, participants in sides.items():
        if set(participants) != {False, True}:
            raise HistoricalFplImportError(f"fixture {fixture_id} does not contain both teams")
        output[fixture_id] = (
            participants[True].club_uuid,
            participants[False].club_uuid,
            kickoffs[fixture_id],
        )
    return output


async def _matches(
    session: AsyncSession,
    *,
    season: Season,
    external_season: str,
    fixtures: dict[str, tuple[UUID, UUID, datetime]],
    observed_at: datetime,
) -> tuple[dict[str, Match], int]:
    canonical = list(
        await session.scalars(select(Match).where(Match.season_uuid == season.season_uuid))
    )
    by_pair: dict[tuple[UUID, UUID], Match] = {}
    for match in canonical:
        key = (match.home_club_uuid, match.away_club_uuid)
        if key in by_pair:
            raise HistoricalFplImportError(f"season {season.label} has duplicate club pairing")
        by_pair[key] = match
    existing_refs = {
        reference.external_fixture_id: reference
        for reference in await session.scalars(
            select(MatchExternalReference).where(MatchExternalReference.provider == PROVIDER)
        )
    }
    mapped: dict[str, Match] = {}
    created = 0
    for fixture_id, (home_uuid, away_uuid, kickoff) in fixtures.items():
        external_id = f"{external_season}:{fixture_id}"
        resolved_match = by_pair.get((home_uuid, away_uuid))
        if resolved_match is None:
            raise HistoricalFplImportError(f"no canonical match for FPL fixture {external_id}")
        if abs((resolved_match.current_kickoff_at - kickoff).total_seconds()) > 36 * 3600:
            raise HistoricalFplImportError(f"kickoff mismatch for FPL fixture {external_id}")
        existing = existing_refs.get(external_id)
        if existing is not None and existing.match_uuid != resolved_match.match_uuid:
            raise HistoricalFplImportError(f"fixture identity conflict for {external_id}")
        if existing is None:
            session.add(
                MatchExternalReference(
                    match_uuid=resolved_match.match_uuid,
                    provider=PROVIDER,
                    external_fixture_id=external_id,
                    observed_from=observed_at,
                )
            )
            created += 1
        mapped[fixture_id] = resolved_match
    return mapped, created


async def _players(
    session: AsyncSession, *, season: ArchivedSeason
) -> tuple[dict[str, Player], int, int]:
    references = {
        reference.external_player_id: reference
        for reference in await session.scalars(
            select(PlayerExternalReference).where(PlayerExternalReference.provider == PROVIDER)
        )
    }
    players_by_uuid = {
        player.player_uuid: player for player in await session.scalars(select(Player))
    }
    mapped: dict[str, Player] = {}
    players_created = 0
    references_created = 0
    stable_seen: dict[str, str] = {}
    for row in season.players.parsed.rows:
        element_id = row.get("id", "").strip()
        stable_code = row.get(season.stable_player_code_column, "").strip()
        if not element_id or not stable_code:
            raise HistoricalFplImportError(f"{season.season} player registry has blank identity")
        name = _canonical_name(row)
        if stable_code in stable_seen and stable_seen[stable_code] != name:
            raise HistoricalFplImportError(f"duplicate stable player code {stable_code}")
        stable_seen[stable_code] = name
        reference = references.get(stable_code)
        if reference is None:
            player = Player(player_uuid=uuid4(), canonical_name=name)
            session.add(player)
            session.add(
                PlayerExternalReference(
                    player_uuid=player.player_uuid,
                    provider=PROVIDER,
                    external_player_id=stable_code,
                    observed_from=season.players.retrieved_at,
                )
            )
            references_created += 1
            players_created += 1
            players_by_uuid[player.player_uuid] = player
        else:
            resolved_player = players_by_uuid.get(reference.player_uuid)
            if resolved_player is None:
                raise HistoricalFplImportError(f"player reference {stable_code} is orphaned")
            player = resolved_player
        mapped[element_id] = player
    await session.flush()
    return mapped, players_created, references_created


async def import_historical_fpl_seasons(
    session: AsyncSession,
    *,
    seasons: tuple[ArchivedSeason, ...],
    alias_registry_path: Path,
) -> HistoricalFplImportSummary:
    """Import audited rows without training or same-fixture market information."""

    clubs = await seed_reviewed_aliases(
        session, provider=PROVIDER, registry_path=alias_registry_path
    )
    totals = {
        "source_files_registered": 0,
        "fixture_references_created": 0,
        "players_created": 0,
        "player_references_created": 0,
        "performances_created": 0,
        "performances_reused": 0,
        "observed_start_records": 0,
        "unknown_start_records": 0,
    }
    for archived in seasons:
        label = _season_label(archived.season)
        season = await session.scalar(select(Season).where(Season.label == label))
        if season is None:
            raise HistoricalFplImportError(f"canonical season {label} is missing")
        sources: dict[str, HistoricalSourceFile] = {}
        for source in (archived.merged, archived.players, archived.fixtures):
            registered, created = await _source_file(session, season_label=label, source=source)
            sources[source.kind] = registered
            totals["source_files_registered"] += int(created)
        fixture_map = _fixture_teams(archived.merged.parsed.rows, clubs)
        matches, references_created = await _matches(
            session,
            season=season,
            external_season=archived.season,
            fixtures=fixture_map,
            observed_at=archived.fixtures.retrieved_at,
        )
        totals["fixture_references_created"] += references_created
        players, created_players, created_refs = await _players(session, season=archived)
        totals["players_created"] += created_players
        totals["player_references_created"] += created_refs
        source_file = sources["merged"]
        existing_rows = {
            performance.source_row_number: performance
            for performance in await session.scalars(
                select(PlayerMatchPerformance).where(
                    PlayerMatchPerformance.source_file_uuid == source_file.source_file_uuid
                )
            )
        }
        canonical_existing = {
            (performance.match_uuid, performance.club_uuid, performance.player_uuid): performance
            for performance in await session.scalars(
                select(PlayerMatchPerformance)
                .join(Match, Match.match_uuid == PlayerMatchPerformance.match_uuid)
                .where(Match.season_uuid == season.season_uuid)
            )
        }
        for row_number, row in enumerate(archived.merged.parsed.rows, 2):
            minutes = _integer(row.get("minutes", ""), field="minutes", row_number=row_number)
            if minutes <= 0:
                continue
            fixture_id = row.get("fixture", "").strip()
            element_id = row.get("element", "").strip()
            match = matches.get(fixture_id)
            player = players.get(element_id)
            if match is None or player is None:
                raise HistoricalFplImportError(f"row {row_number}: unresolved match or player")
            club = resolve_club(clubs, row.get("team", ""))
            if club.club_uuid not in (match.home_club_uuid, match.away_club_uuid):
                raise HistoricalFplImportError(f"row {row_number}: player club is not in fixture")
            checksum = _row_checksum(row)
            existing = existing_rows.get(row_number)
            if existing is not None:
                if existing.row_checksum != checksum:
                    raise HistoricalFplImportError(f"row {row_number}: immutable source changed")
                totals["performances_reused"] += 1
                continue
            canonical_key = (match.match_uuid, club.club_uuid, player.player_uuid)
            collision = canonical_existing.get(canonical_key)
            if (
                collision is not None
                and collision.source_file_uuid == source_file.source_file_uuid
                and collision.row_checksum == checksum
            ):
                totals["performances_reused"] += 1
                continue
            if collision is not None:
                raise HistoricalFplImportError(
                    f"row {row_number}: canonical performance already belongs to another source"
                )
            start_value = row.get("starts", "").strip()
            if archived.start_indicator_available and start_value:
                started: bool | None = bool(
                    _integer(start_value, field="starts", row_number=row_number)
                )
                start_source = "observed"
                totals["observed_start_records"] += 1
            else:
                started = None
                start_source = "unknown"
                totals["unknown_start_records"] += 1
            position = POSITION_MAP.get(row.get("position", "").strip().upper())
            if position is None:
                raise HistoricalFplImportError(f"row {row_number}: invalid position")
            statistics = {
                target: _number(row.get(source, ""))
                for source, target in SAFE_STATISTICS.items()
                if row.get(source, "") != ""
            }
            performance = PlayerMatchPerformance(
                match_uuid=match.match_uuid,
                club_uuid=club.club_uuid,
                player_uuid=player.player_uuid,
                started=started,
                starting_status_source=start_source,
                position=position,
                minutes=minutes,
                rating=None,
                statistics=statistics,
                available_after=match.current_kickoff_at + timedelta(hours=4),
                provider=PROVIDER,
                provider_payload_key=archived.merged.object_key,
                source_file_uuid=source_file.source_file_uuid,
                source_row_number=row_number,
                row_checksum=checksum,
            )
            session.add(performance)
            canonical_existing[canonical_key] = performance
            totals["performances_created"] += 1
        await session.flush()
    await session.flush()
    return HistoricalFplImportSummary(seasons_imported=len(seasons), **totals)
