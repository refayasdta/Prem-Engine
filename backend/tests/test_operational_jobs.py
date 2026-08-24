"""Background standings persistence and current player-context ingestion."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from prem_engine_api.domain.enums import FixtureStatus
from prem_engine_api.domain.models import (
    Club,
    ClubExternalReference,
    Competition,
    Match,
    MatchExternalReference,
    ObservedLineupPlayer,
    PlayerAvailabilityReport,
    PlayerMatchPerformance,
    Season,
    SeasonClub,
    SquadMembership,
    TransferObservation,
)
from prem_engine_api.ingestion.player_context import PlayerContextIngestor
from prem_engine_api.ingestion.player_sync import (
    _club_targets,
    _next_cursor,
    _squad_request_params,
    _squad_snapshot_is_usable,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _season_and_match(
    session: AsyncSession,
) -> tuple[Season, Club, Club, Match, datetime]:
    competition = Competition(slug="ops", name="Premier League", country_code="GB")
    home = Club(canonical_name="Operational Home", short_name="OPH")
    away = Club(canonical_name="Operational Away", short_name="OPA")
    session.add_all((competition, home, away))
    await session.flush()
    season = Season(
        competition_uuid=competition.competition_uuid,
        label="2026/27",
        start_date=date(2026, 8, 1),
        end_date=date(2027, 5, 31),
    )
    session.add(season)
    await session.flush()
    session.add_all(
        (
            SeasonClub(season_uuid=season.season_uuid, club_uuid=home.club_uuid),
            SeasonClub(season_uuid=season.season_uuid, club_uuid=away.club_uuid),
            ClubExternalReference(
                club_uuid=home.club_uuid,
                provider="kickoffapi",
                external_club_id="tm_home",
                observed_from=datetime(2026, 8, 1, tzinfo=UTC),
            ),
            ClubExternalReference(
                club_uuid=away.club_uuid,
                provider="kickoffapi",
                external_club_id="tm_away",
                observed_from=datetime(2026, 8, 1, tzinfo=UTC),
            ),
        )
    )
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    match = Match(
        season_uuid=season.season_uuid,
        home_club_uuid=home.club_uuid,
        away_club_uuid=away.club_uuid,
        status=FixtureStatus.FINISHED,
        current_kickoff_at=now - timedelta(days=1),
        prediction_due_at=now - timedelta(days=2),
    )
    session.add(match)
    await session.flush()
    session.add(
        MatchExternalReference(
            match_uuid=match.match_uuid,
            provider="kickoffapi",
            external_fixture_id="fx_1",
            observed_from=now - timedelta(days=10),
        )
    )
    await session.flush()
    return season, home, away, match, now


def test_player_context_cursor_is_tolerant_and_explicit() -> None:
    assert _next_cursor({"meta": {"nextCursor": "page-2"}}) == "page-2"
    assert _next_cursor({"meta": {"next_cursor": 3}}) == "3"
    assert _next_cursor({"meta": {"nextCursor": None}}) is None
    assert _next_cursor([]) is None


def test_squad_requests_are_scoped_to_the_active_season() -> None:
    assert _squad_request_params(2026) == {"season": 2026}


def test_squad_snapshots_must_be_plausible_for_the_requested_season() -> None:
    players = [
        {
            "id": index,
            "name": f"Player {index}",
            "position": "Goalkeeper" if index == 1 else "Midfielder",
        }
        for index in range(1, 21)
    ]
    oversized = [
        {
            "id": index,
            "name": f"Player {index}",
            "position": "Goalkeeper" if index == 1 else "Midfielder",
        }
        for index in range(1, 52)
    ]
    assert _squad_snapshot_is_usable({"meta": {"season": "2026"}, "data": players}, 2026)
    assert not _squad_snapshot_is_usable({"meta": {"season": None}, "data": players}, 2026)
    assert not _squad_snapshot_is_usable({"meta": {"season": 2026}, "data": players[:10]}, 2026)
    assert not _squad_snapshot_is_usable({"meta": {"season": 2026}, "data": oversized}, 2026)
    assert not _squad_snapshot_is_usable(
        {
            "meta": {"season": 2026},
            "data": [{**player, "position": "Midfielder"} for player in players],
        },
        2026,
    )


@pytest.mark.asyncio
async def test_player_sync_prioritizes_unsynchronized_clubs_in_next_fixture(
    db_session: AsyncSession,
) -> None:
    season, home, away, match, now = await _season_and_match(db_session)
    match.status = FixtureStatus.SCHEDULED
    match.current_kickoff_at = now + timedelta(hours=18)
    match.prediction_due_at = match.current_kickoff_at - timedelta(days=1)
    later_home = Club(canonical_name="Later Home", short_name="LTH")
    later_away = Club(canonical_name="Later Away", short_name="LTA")
    db_session.add_all((later_home, later_away))
    await db_session.flush()
    db_session.add_all(
        (
            SeasonClub(season_uuid=season.season_uuid, club_uuid=later_home.club_uuid),
            SeasonClub(season_uuid=season.season_uuid, club_uuid=later_away.club_uuid),
            ClubExternalReference(
                club_uuid=later_home.club_uuid,
                provider="kickoffapi",
                external_club_id="tm_later_home",
                observed_from=now,
            ),
            ClubExternalReference(
                club_uuid=later_away.club_uuid,
                provider="kickoffapi",
                external_club_id="tm_later_away",
                observed_from=now,
            ),
            Match(
                season_uuid=season.season_uuid,
                home_club_uuid=later_home.club_uuid,
                away_club_uuid=later_away.club_uuid,
                status=FixtureStatus.SCHEDULED,
                current_kickoff_at=now + timedelta(days=2),
                prediction_due_at=now + timedelta(days=1),
            ),
        )
    )
    await db_session.flush()

    targets = await _club_targets(
        db_session,
        season_uuid=season.season_uuid,
        limit=2,
        now=now,
    )

    assert set(targets) == {
        (home.club_uuid, "tm_home"),
        (away.club_uuid, "tm_away"),
    }


@pytest.mark.asyncio
async def test_player_context_ingestion_populates_canonical_lineup_inputs(
    db_session: AsyncSession,
) -> None:
    season, home, away, match, now = await _season_and_match(db_session)
    ingestor = PlayerContextIngestor(db_session)

    squad = await ingestor.ingest_squad(
        {
            "data": [
                {"id": "pl_1", "name": "Ada Keeper", "position": "Goalkeeper", "number": 1},
                {"id": "pl_2", "name": "Bea Forward", "position": "Attacker", "number": 9},
            ]
        },
        season_uuid=season.season_uuid,
        club_uuid=home.club_uuid,
        observed_at=now,
    )
    assert squad.created == 2

    injury = await ingestor.ingest_injuries(
        {
            "data": [
                {
                    "id": 7,
                    "player": {"id": "pl_2", "name": "Bea Forward"},
                    "team": {"id": "tm_home", "name": "Operational Home"},
                    "fixture": {"id": "fx_1"},
                    "injury": {"type": "Suspension", "until": "2026-08-20"},
                }
            ]
        },
        observed_at=now,
        provider_payload_key="raw-1",
    )
    assert injury.created == 1

    transfer = await ingestor.ingest_transfers(
        {
            "data": [
                {
                    "id": "tr_1",
                    "date": "2026-08-11",
                    "type": "Transfer",
                    "player": {"id": "pl_2", "name": "Bea Forward"},
                    "teams": {
                        "out": {"id": "tm_home"},
                        "in": {"id": "tm_away"},
                    },
                },
                {
                    "id": "placeholder-no-date",
                    "date": None,
                    "player": {"id": None, "name": None},
                },
                {
                    "id": "placeholder-no-player",
                    "date": "2026-08-12",
                    "player": {"id": None, "name": None},
                },
            ]
        },
        observed_at=now,
        provider_payload_key="raw-2",
    )
    assert transfer.created == 1
    assert transfer.received == 3
    assert transfer.unresolved == 2

    lineup = await ingestor.ingest_lineups(
        {
            "data": [
                {
                    "team": {"id": "tm_home", "name": "Operational Home"},
                    "formation": "4-3-3",
                    "startXI": [{"player": {"id": "pl_1", "name": "Ada Keeper"}, "pos": "G"}],
                    "substitutes": [{"player": {"id": "pl_2", "name": "Bea Forward"}, "pos": "F"}],
                }
            ]
        },
        match_uuid=match.match_uuid,
        observed_at=now,
        provider_payload_key="raw-3",
    )
    assert lineup.created == 2

    performances = await ingestor.ingest_performances(
        {
            "data": [
                {
                    "team": {"id": "tm_home"},
                    "players": [
                        {
                            "player": {"id": "pl_1", "name": "Ada Keeper"},
                            "statistics": [
                                {
                                    "games": {
                                        "minutes": 90,
                                        "rating": "7.2",
                                        "position": "G",
                                        "substitute": False,
                                    },
                                    "goals": {"total": 0},
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        match_uuid=match.match_uuid,
        observed_at=now,
        provider_payload_key="raw-4",
    )
    assert performances.created == 1
    assert await db_session.scalar(select(func.count()).select_from(SquadMembership)) == 2
    assert await db_session.scalar(select(func.count()).select_from(PlayerAvailabilityReport)) == 1
    assert await db_session.scalar(select(func.count()).select_from(TransferObservation)) == 1
    assert await db_session.scalar(select(func.count()).select_from(ObservedLineupPlayer)) == 2
    performance = await db_session.scalar(select(PlayerMatchPerformance))
    assert performance is not None
    assert performance.started is True
    assert performance.minutes == 90
