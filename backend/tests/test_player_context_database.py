"""Database invariants for Phase 10 player context."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from prem_engine_api.domain.enums import FixtureStatus, PlayerAvailabilityStatus
from prem_engine_api.domain.models import (
    Club,
    Competition,
    Match,
    ObservedLineup,
    ObservedLineupPlayer,
    Player,
    PlayerAvailabilityReport,
    PlayerMatchPerformance,
    Season,
    TransferObservation,
)
from prem_engine_api.player_context import export_player_context
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_player_context_round_trip_and_probability_constraint(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    competition = Competition(slug="phase-10", name="Phase 10 League", country_code="GB")
    home = Club(canonical_name="Phase 10 Home", short_name="P10 Home")
    away = Club(canonical_name="Phase 10 Away", short_name="P10 Away")
    player = Player(canonical_name="Phase 10 Player", nationality_code="GBR")
    db_session.add_all((competition, home, away, player))
    await db_session.flush()
    season = Season(
        competition_uuid=competition.competition_uuid,
        label="2026/27",
        start_date=date(2026, 8, 1),
        end_date=date(2027, 5, 31),
    )
    db_session.add(season)
    await db_session.flush()
    kickoff = datetime(2026, 8, 15, 14, tzinfo=UTC)
    match = Match(
        season_uuid=season.season_uuid,
        home_club_uuid=home.club_uuid,
        away_club_uuid=away.club_uuid,
        status=FixtureStatus.FINISHED,
        current_kickoff_at=kickoff,
        prediction_due_at=kickoff - timedelta(hours=24),
    )
    db_session.add(match)
    await db_session.flush()

    lineup = ObservedLineup(
        match_uuid=match.match_uuid,
        club_uuid=home.club_uuid,
        formation="4-3-3",
        confirmed=True,
        observed_at=kickoff - timedelta(minutes=75),
        available_after=kickoff - timedelta(minutes=75),
        provider="kickoffapi",
        provider_payload_key="raw/lineup-1.json.gz",
        checksum="a" * 64,
    )
    db_session.add(lineup)
    await db_session.flush()
    db_session.add_all(
        (
            ObservedLineupPlayer(
                observed_lineup_uuid=lineup.observed_lineup_uuid,
                player_uuid=player.player_uuid,
                role="starter",
                slot=1,
                position="G",
                shirt_number=1,
            ),
            PlayerMatchPerformance(
                match_uuid=match.match_uuid,
                club_uuid=home.club_uuid,
                player_uuid=player.player_uuid,
                started=True,
                position="G",
                minutes=90,
                rating=Decimal("7.20"),
                statistics={"saves": 4},
                available_after=kickoff + timedelta(hours=2),
                provider_payload_key="raw/player-stats-1.json.gz",
            ),
            PlayerAvailabilityReport(
                player_uuid=player.player_uuid,
                club_uuid=home.club_uuid,
                match_uuid=match.match_uuid,
                status=PlayerAvailabilityStatus.AVAILABLE,
                reason=None,
                availability_probability=Decimal("1.0000"),
                reported_at=kickoff - timedelta(days=1),
                expected_return_at=None,
                observed_at=kickoff - timedelta(days=1),
                provider="kickoffapi",
                provider_payload_key="raw/injury-1.json.gz",
            ),
            TransferObservation(
                player_uuid=player.player_uuid,
                from_club_uuid=away.club_uuid,
                to_club_uuid=home.club_uuid,
                transfer_date=date(2026, 7, 1),
                transfer_type="Transfer",
                external_transfer_id="tr_1",
                observed_at=datetime(2026, 7, 2, tzinfo=UTC),
                provider="kickoffapi",
                provider_payload_key="raw/transfer-1.json.gz",
            ),
        )
    )
    await db_session.flush()

    restored = await db_session.scalar(
        select(PlayerMatchPerformance).where(
            PlayerMatchPerformance.player_uuid == player.player_uuid
        )
    )
    assert restored is not None
    assert restored.minutes == 90

    exported = await export_player_context(db_session, output_root=tmp_path)
    assert exported.performance_count == 1
    assert exported.availability_count == 1
    assert exported.transfer_count == 1
    assert exported.performance_path.read_text(encoding="utf-8").count("\n") == 2

    invalid = PlayerAvailabilityReport(
        player_uuid=player.player_uuid,
        club_uuid=home.club_uuid,
        match_uuid=None,
        status=PlayerAvailabilityStatus.UNKNOWN,
        reason=None,
        availability_probability=Decimal("1.2000"),
        reported_at=None,
        expected_return_at=None,
        observed_at=kickoff,
        provider="test",
        provider_payload_key="raw/invalid.json.gz",
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(invalid)
            await db_session.flush()
