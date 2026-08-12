"""Real-artifact integration coverage for the rollback-only T-24 rehearsal."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import FixtureStatus
from prem_engine_api.domain.models import (
    Club,
    Competition,
    JobRun,
    Match,
    Player,
    PredictionVersion,
    Season,
    SquadMembership,
    StoredSimulation,
)
from prem_engine_api.operations.t24_rehearsal import T24RehearsalError, rehearse_t24_forecast
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _settings(*, app_env: str = "test") -> Settings:
    return Settings(
        app_env=app_env,
        goal_model_path=(
            PROJECT_ROOT / "artifacts/models/goals/goals-v1-156511483a94/model.joblib"
        ),
        statistics_model_path=(
            PROJECT_ROOT / "artifacts/models/match-statistics/"
            "detailed-statistics-v1-42e73adec486/model.joblib"
        ),
    )


async def _seed_rehearsal_match(session: AsyncSession) -> Match:
    competition = Competition(slug="t24-rehearsal", name="Rehearsal League", country_code="GB")
    home = Club(canonical_name="Rehearsal Home", short_name="RHM")
    away = Club(canonical_name="Rehearsal Away", short_name="RAW")
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

    kickoff = datetime(2026, 9, 12, 15, 0, tzinfo=UTC)
    match = Match(
        season_uuid=season.season_uuid,
        home_club_uuid=home.club_uuid,
        away_club_uuid=away.club_uuid,
        status=FixtureStatus.SCHEDULED,
        current_kickoff_at=kickoff,
        prediction_due_at=kickoff - timedelta(hours=24),
    )
    session.add(match)
    await session.flush()

    positions = (
        "goalkeeper",
        "defender",
        "defender",
        "defender",
        "defender",
        "defender",
        "midfielder",
        "midfielder",
        "midfielder",
        "midfielder",
        "midfielder",
        "forward",
        "forward",
        "forward",
        "forward",
        "forward",
        "forward",
        "forward",
    )
    for club, prefix in ((home, "Home"), (away, "Away")):
        for index, position in enumerate(positions, 1):
            player = Player(canonical_name=f"{prefix} Rehearsal Player {index:02d}")
            session.add(player)
            await session.flush()
            session.add(
                SquadMembership(
                    season_uuid=season.season_uuid,
                    club_uuid=club.club_uuid,
                    player_uuid=player.player_uuid,
                    joined_on=season.start_date,
                    shirt_number=index,
                    primary_position=position,
                )
            )
    await session.flush()
    return match


@pytest.mark.asyncio
async def test_real_artifacts_complete_the_transactional_t24_rehearsal(
    db_session: AsyncSession,
) -> None:
    match = await _seed_rehearsal_match(db_session)

    report = await rehearse_t24_forecast(
        db_session,
        settings=_settings(),
        match_uuid=match.match_uuid,
    )

    assert report.match_uuid == match.match_uuid
    assert report.home_starters == report.away_starters == 11
    assert report.home_substitutes >= 3
    assert report.away_substitutes >= 3
    assert report.outcome_model_version.startswith("goals-v1-")
    assert report.statistics_model_version.startswith("detailed-statistics-v1-")
    assert report.simulation_event_count > 0
    assert report.live_state == "live"
    assert report.complete_state == "complete"
    assert report.final_score_withheld_while_live is True
    assert report.final_score_revealed_when_complete is True
    assert await db_session.scalar(select(func.count()).select_from(PredictionVersion)) == 1
    assert await db_session.scalar(select(func.count()).select_from(StoredSimulation)) == 1
    assert await db_session.scalar(select(func.count()).select_from(JobRun)) == 2


@pytest.mark.asyncio
async def test_rehearsal_refuses_production(db_session: AsyncSession) -> None:
    match = await _seed_rehearsal_match(db_session)

    with pytest.raises(T24RehearsalError, match="disabled in production"):
        await rehearse_t24_forecast(
            db_session,
            settings=_settings(app_env="production"),
            match_uuid=match.match_uuid,
        )
