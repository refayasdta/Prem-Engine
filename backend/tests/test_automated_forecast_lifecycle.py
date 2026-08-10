"""Phase 14 job leases, atomic locking, and synchronized public reads."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from prem_engine_api.api.forecasts import build_match_forecast_response
from prem_engine_api.domain.enums import FixtureStatus, JobStatus
from prem_engine_api.domain.models import (
    Club,
    Competition,
    FeatureSnapshot,
    FixtureScheduleRevision,
    JobRun,
    LifecycleEvent,
    Match,
    Player,
    PlayerMatchPerformance,
    PredictionVersion,
    Season,
    StoredSimulation,
)
from prem_engine_api.forecasting.contracts import (
    FeatureSnapshotInput,
    ForecastPackage,
    LineupPlayer,
    ModelForecast,
    TeamLineup,
)
from prem_engine_api.forecasting.generation import lock_forecast
from prem_engine_api.forecasting.lineups import expected_lineup_for_club
from prem_engine_api.jobs.leases import (
    GENERATE_PREDICTION_JOB,
    claim_due_jobs,
    enqueue_prediction_jobs,
    start_job,
)
from prem_engine_modeling.goals import forecast_from_rates
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_due_match(session: AsyncSession) -> tuple[Match, Club, Club, datetime]:
    competition = Competition(slug="phase-14", name="Premier League", country_code="GB")
    home = Club(canonical_name="North London FC", short_name="NLF")
    away = Club(canonical_name="Mersey United", short_name="MER")
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
    kickoff = datetime(2026, 9, 2, 19, 0, tzinfo=UTC)
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
    session.add(
        FixtureScheduleRevision(
            match_uuid=match.match_uuid,
            revision_number=1,
            kickoff_at=kickoff,
            canonical_status=FixtureStatus.SCHEDULED,
            provider_status="NS",
            observed_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
    )
    await session.flush()
    return match, home, away, match.prediction_due_at


def _lineup(club: Club, prefix: str) -> TeamLineup:
    positions = ("GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "FWD", "FWD", "FWD")

    def player(index: int, position: str, *, substitute: bool = False) -> LineupPlayer:
        return LineupPlayer(
            player_uuid=uuid4(),
            name=f"{prefix} {'Substitute' if substitute else 'Starter'} {index}",
            position=position,  # type: ignore[arg-type]
            shirt_number=index + (20 if substitute else 0),
            shirt_number_source="observed",
            starting_probability=0.85 if not substitute else 0.25,
            availability_probability=1.0,
        )

    return TeamLineup(
        club_uuid=club.club_uuid,
        club_name=club.canonical_name,
        short_name=club.short_name,
        formation="4-3-3",
        starters=tuple(player(index, position) for index, position in enumerate(positions, 1)),
        substitutes=tuple(player(index, "MID", substitute=True) for index in range(1, 6)),
        confidence=0.81,
    )


def _package(match: Match, home: Club, away: Club, cutoff: datetime) -> ForecastPackage:
    goals = forecast_from_rates(1.6, 1.2, dixon_coles_rho=-0.08)
    means = {
        f"{side}_{name}": value
        for side in ("home", "away")
        for name, value in (
            ("half_time_goals", 0.6),
            ("shots", 12.0),
            ("shots_on_target", 4.0),
            ("corners", 5.0),
            ("fouls", 10.0),
            ("yellow_cards", 1.5),
            ("red_cards", 0.05),
        )
    }
    return ForecastPackage(
        match_uuid=match.match_uuid,
        feature_snapshot=FeatureSnapshotInput(
            schema_version="test-v1",
            feature_cutoff_at=cutoff,
            latest_source_observed_at=cutoff - timedelta(minutes=1),
            payload={"source": "test", "feature": 1.0},
        ),
        forecast=ModelForecast(
            outcome_model_version="goals-v1-test",
            statistics_model_version="statistics-v1-test",
            expected_home_goals=1.6,
            expected_away_goals=1.2,
            score_matrix=goals.score_matrix,
            statistic_means=means,
            statistic_intervals_90={key: (0.0, value + 3.0) for key, value in means.items()},
        ),
        home_lineup=_lineup(home, "Home"),
        away_lineup=_lineup(away, "Away"),
        random_seed=20260810,
    )


@pytest.mark.asyncio
async def test_jobs_are_enqueued_once_and_claimed_once(db_session: AsyncSession) -> None:
    match, _, _, due = await _seed_due_match(db_session)

    assert await enqueue_prediction_jobs(db_session, now=due) == 1
    assert await enqueue_prediction_jobs(db_session, now=due) == 0
    claimed = await claim_due_jobs(
        db_session,
        worker_id="worker-a",
        now=due,
        lease_duration=timedelta(minutes=5),
        limit=10,
        max_attempts=4,
        job_types=(GENERATE_PREDICTION_JOB,),
    )
    second_claim = await claim_due_jobs(
        db_session,
        worker_id="worker-b",
        now=due,
        lease_duration=timedelta(minutes=5),
        limit=10,
        max_attempts=4,
        job_types=(GENERATE_PREDICTION_JOB,),
    )

    assert len(claimed) == 1
    assert claimed[0].match_uuid == match.match_uuid
    assert second_claim == ()


@pytest.mark.asyncio
async def test_forecast_is_locked_atomically_and_generation_is_idempotent(
    db_session: AsyncSession,
) -> None:
    match, home, away, due = await _seed_due_match(db_session)
    await enqueue_prediction_jobs(db_session, now=due)
    claimed = await claim_due_jobs(
        db_session,
        worker_id="worker-a",
        now=due,
        lease_duration=timedelta(minutes=5),
        limit=1,
        max_attempts=4,
        job_types=(GENERATE_PREDICTION_JOB,),
    )
    await start_job(
        db_session,
        job_uuid=claimed[0].job_uuid,
        worker_id="worker-a",
        now=due,
    )
    package = _package(match, home, away, due)
    outcome = await lock_forecast(
        db_session,
        job_uuid=claimed[0].job_uuid,
        worker_id="worker-a",
        package=package,
        locked_at=due + timedelta(seconds=2),
    )

    assert outcome.created is True
    assert await db_session.scalar(select(func.count()).select_from(PredictionVersion)) == 1
    snapshot = await db_session.scalar(
        select(FeatureSnapshot).where(
            FeatureSnapshot.prediction_version_uuid == outcome.prediction_version_uuid
        )
    )
    assert snapshot is not None
    simulation = await db_session.scalar(
        select(StoredSimulation).where(
            StoredSimulation.prediction_version_uuid == outcome.prediction_version_uuid
        )
    )
    assert simulation is not None
    assert simulation.presentation_duration_seconds == 60
    assert await db_session.scalar(select(func.count()).select_from(LifecycleEvent)) == 1

    with pytest.raises(DBAPIError), db_session.no_autoflush:
        async with db_session.begin_nested():
            snapshot.feature_payload = {"tampered": True}
            await db_session.flush()

    duplicate_job = JobRun(
        idempotency_key=f"duplicate-test:{match.match_uuid}",
        job_type=GENERATE_PREDICTION_JOB,
        status=JobStatus.RUNNING,
        match_uuid=match.match_uuid,
        due_at=due,
        lease_owner="worker-b",
        lease_expires_at=due + timedelta(minutes=5),
        attempt_count=1,
        started_at=due,
    )
    db_session.add(duplicate_job)
    await db_session.flush()
    reused = await lock_forecast(
        db_session,
        job_uuid=duplicate_job.job_uuid,
        worker_id="worker-b",
        package=package,
        locked_at=due + timedelta(seconds=3),
    )
    assert reused.created is False
    assert reused.prediction_version_uuid == outcome.prediction_version_uuid
    assert await db_session.scalar(select(func.count()).select_from(PredictionVersion)) == 1


@pytest.mark.asyncio
async def test_public_read_reveals_only_the_synchronized_timeline(
    db_session: AsyncSession,
) -> None:
    match, home, away, due = await _seed_due_match(db_session)
    job = JobRun(
        idempotency_key=f"read-test:{match.match_uuid}",
        job_type=GENERATE_PREDICTION_JOB,
        status=JobStatus.RUNNING,
        match_uuid=match.match_uuid,
        due_at=due,
        lease_owner="worker",
        lease_expires_at=due + timedelta(minutes=5),
        attempt_count=1,
        started_at=due,
    )
    db_session.add(job)
    await db_session.flush()
    locked_at = due + timedelta(seconds=1)
    await lock_forecast(
        db_session,
        job_uuid=job.job_uuid,
        worker_id="worker",
        package=_package(match, home, away, due),
        locked_at=locked_at,
    )

    live = await build_match_forecast_response(
        db_session,
        match_uuid=match.match_uuid,
        now=locked_at + timedelta(seconds=10),
    )
    complete = await build_match_forecast_response(
        db_session,
        match_uuid=match.match_uuid,
        now=locked_at + timedelta(seconds=61),
    )

    assert live is not None and live.lifecycle_state == "live"
    assert live.simulation is not None and live.simulation.final_score is None
    assert all(
        int(event["minute"]) * 60 + int(event["second"]) <= live.presentation.football_second
        for event in live.simulation.events
    )
    assert complete is not None and complete.lifecycle_state == "complete"
    assert complete.simulation is not None
    assert complete.simulation.final_score is not None


def test_snapshot_rejects_data_at_the_cutoff() -> None:
    cutoff = datetime(2026, 8, 10, tzinfo=UTC)

    with pytest.raises(ValueError, match="at or after"):
        FeatureSnapshotInput(
            schema_version="test-v1",
            feature_cutoff_at=cutoff,
            latest_source_observed_at=cutoff,
            payload={},
        )


@pytest.mark.asyncio
async def test_expected_lineup_uses_canonical_player_names_without_inventing_ids(
    db_session: AsyncSession,
) -> None:
    match, home, _, cutoff = await _seed_due_match(db_session)
    history_match = Match(
        season_uuid=match.season_uuid,
        home_club_uuid=home.club_uuid,
        away_club_uuid=match.away_club_uuid,
        status=FixtureStatus.FINISHED,
        current_kickoff_at=match.current_kickoff_at - timedelta(days=30),
        prediction_due_at=match.prediction_due_at - timedelta(days=30),
    )
    db_session.add(history_match)
    await db_session.flush()
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
        "attacker",
        "attacker",
        "attacker",
        "attacker",
        "attacker",
    )
    canonical_ids: set[UUID] = set()
    for index, position in enumerate(positions, 1):
        player = Player(canonical_name=f"Canonical Player {index}")
        db_session.add(player)
        await db_session.flush()
        canonical_ids.add(player.player_uuid)
        db_session.add(
            PlayerMatchPerformance(
                match_uuid=history_match.match_uuid,
                club_uuid=home.club_uuid,
                player_uuid=player.player_uuid,
                started=index <= 11,
                starting_status_source="observed",
                position=position,
                minutes=90 if index <= 11 else 20,
                rating=Decimal("6.50"),
                statistics={"goals": 0, "assists": 0},
                available_after=history_match.current_kickoff_at + timedelta(hours=4),
                provider="test",
                provider_payload_key=f"test/player/{index}",
            )
        )
    await db_session.flush()

    lineup, latest_used = await expected_lineup_for_club(
        db_session,
        match_uuid=match.match_uuid,
        season_uuid=match.season_uuid,
        club_uuid=home.club_uuid,
        club_name=home.canonical_name,
        short_name=home.short_name,
        kickoff_at=match.current_kickoff_at,
        cutoff=cutoff,
    )

    selected = lineup.starters + lineup.substitutes
    assert len(lineup.starters) == 11
    assert len(lineup.substitutes) == 5
    assert {player.player_uuid for player in selected} <= canonical_ids
    assert all(player.name.startswith("Canonical Player") for player in selected)
    assert all(player.shirt_number_source == "presentation_slot" for player in selected)
    assert latest_used is not None and latest_used < cutoff
