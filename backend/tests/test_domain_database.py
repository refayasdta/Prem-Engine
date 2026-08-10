"""PostgreSQL invariants for the Phase 3 domain schema."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from prem_engine_api.domain.enums import FixtureStatus, PredictionState
from prem_engine_api.domain.lifecycle import cancel_match, reschedule_match
from prem_engine_api.domain.models import (
    Club,
    Competition,
    FixtureScheduleRevision,
    JobRun,
    Match,
    PredictedLineup,
    PredictionVersion,
    Season,
    StoredSimulation,
)
from prem_engine_api.domain.request_budget import (
    RequestBudgetExhaustedError,
    reserve_request_slot,
)
from sqlalchemy import inspect, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_locked_match(session: AsyncSession) -> tuple[Match, PredictionVersion]:
    competition = Competition(slug="premier-league", name="Premier League", country_code="GB")
    home = Club(canonical_name="Home FC", short_name="Home")
    away = Club(canonical_name="Away FC", short_name="Away")
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

    kickoff = datetime(2026, 9, 1, 19, 0, tzinfo=UTC)
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
    prediction = PredictionVersion(
        match_uuid=match.match_uuid,
        version_number=1,
        state=PredictionState.ACTIVE_LOCKED,
        feature_cutoff_at=kickoff - timedelta(hours=24),
        model_version="phase-3-test",
        feature_snapshot_checksum="a" * 64,
        home_win_probability=Decimal("0.40000000"),
        draw_probability=Decimal("0.30000000"),
        away_win_probability=Decimal("0.30000000"),
        expected_home_goals=Decimal("1.5000"),
        expected_away_goals=Decimal("1.1000"),
        statistics_distribution={},
        locked_at=kickoff - timedelta(hours=24),
    )
    session.add(prediction)
    await session.flush()
    session.add_all(
        (
            PredictedLineup(
                prediction_version_uuid=prediction.prediction_version_uuid,
                formation="4-3-3",
                lineup_payload={"starters": []},
                checksum="b" * 64,
            ),
            StoredSimulation(
                prediction_version_uuid=prediction.prediction_version_uuid,
                random_seed=20260807,
                home_goals=2,
                away_goals=1,
                statistics={},
                events=[],
                checksum="c" * 64,
            ),
        )
    )
    await session.flush()
    return match, prediction


@pytest.mark.asyncio
async def test_migrated_schema_contains_core_tables(db_session: AsyncSession) -> None:
    def table_names(sync_connection: Any) -> set[str]:
        return set(inspect(sync_connection).get_table_names())

    connection = await db_session.connection()
    names = await connection.run_sync(table_names)
    assert {
        "matches",
        "match_external_references",
        "fixture_schedule_revisions",
        "prediction_versions",
        "predicted_lineups",
        "stored_simulations",
        "standings_snapshots",
        "standings_rows",
        "provider_request_budgets",
        "provider_requests",
        "identity_review_cases",
        "competition_external_references",
        "historical_source_files",
        "historical_match_records",
        "club_aliases",
        "observed_lineups",
        "observed_lineup_players",
        "player_match_performances",
        "player_availability_reports",
        "transfer_observations",
        "lifecycle_events",
    } <= names


@pytest.mark.asyncio
async def test_reschedule_voids_prediction_and_keeps_artifacts(db_session: AsyncSession) -> None:
    match, prediction = await seed_locked_match(db_session)
    revised_kickoff = match.current_kickoff_at + timedelta(days=21)

    outcome = await reschedule_match(
        db_session,
        match_uuid=match.match_uuid,
        revised_kickoff_at=revised_kickoff,
        provider_status="TBD",
        actor="test-suite",
        observed_at=datetime(2026, 8, 31, tzinfo=UTC),
    )

    assert outcome.prediction_voided is True
    assert prediction.state is PredictionState.VOIDED
    assert prediction.void_reason == "fixture_postponed"
    assert match.current_kickoff_at == revised_kickoff
    assert match.prediction_due_at == revised_kickoff - timedelta(hours=24)
    jobs = list(
        await db_session.scalars(select(JobRun).where(JobRun.match_uuid == match.match_uuid))
    )
    assert {job.job_type for job in jobs} == {
        "generate_prediction",
        "recalculate_simulated_standings",
    }
    assert await db_session.scalar(
        select(PredictedLineup).where(
            PredictedLineup.prediction_version_uuid == prediction.prediction_version_uuid
        )
    )
    assert await db_session.scalar(
        select(StoredSimulation).where(
            StoredSimulation.prediction_version_uuid == prediction.prediction_version_uuid
        )
    )

    with pytest.raises(DBAPIError), db_session.no_autoflush:
        async with db_session.begin_nested():
            prediction.expected_home_goals = Decimal("9.0000")
            await db_session.flush()


@pytest.mark.asyncio
async def test_only_one_official_prediction_is_active(db_session: AsyncSession) -> None:
    match, _ = await seed_locked_match(db_session)
    duplicate = PredictionVersion(
        match_uuid=match.match_uuid,
        version_number=2,
        state=PredictionState.ACTIVE_LOCKED,
        feature_cutoff_at=match.prediction_due_at,
        model_version="duplicate",
        feature_snapshot_checksum="d" * 64,
        home_win_probability=Decimal("0.40000000"),
        draw_probability=Decimal("0.30000000"),
        away_win_probability=Decimal("0.30000000"),
        expected_home_goals=Decimal("1.0000"),
        expected_away_goals=Decimal("1.0000"),
        statistics_distribution={},
        locked_at=match.prediction_due_at,
    )

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(duplicate)
            await db_session.flush()


@pytest.mark.asyncio
async def test_request_budget_stops_at_operational_limit(db_session: AsyncSession) -> None:
    budget_date = date(2026, 8, 7)
    first = await reserve_request_slot(
        db_session,
        provider="kickoffapi-test",
        budget_date=budget_date,
        operational_limit=2,
        hard_limit=3,
    )
    second = await reserve_request_slot(
        db_session,
        provider="kickoffapi-test",
        budget_date=budget_date,
        operational_limit=2,
        hard_limit=3,
    )
    assert isinstance(first, UUID)
    assert first == second
    with pytest.raises(RequestBudgetExhaustedError):
        await reserve_request_slot(
            db_session,
            provider="kickoffapi-test",
            budget_date=budget_date,
            operational_limit=2,
            hard_limit=3,
        )


@pytest.mark.asyncio
async def test_cancelled_match_voids_without_replacement(db_session: AsyncSession) -> None:
    match, prediction = await seed_locked_match(db_session)
    voided = await cancel_match(
        db_session,
        match_uuid=match.match_uuid,
        provider_status="CANC",
        actor="test-suite",
        observed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert voided is True
    assert match.status is FixtureStatus.CANCELLED
    assert prediction.state is PredictionState.VOIDED
    assert prediction.void_reason == "fixture_cancelled"
    jobs = list(
        await db_session.scalars(select(JobRun).where(JobRun.match_uuid == match.match_uuid))
    )
    assert [job.job_type for job in jobs] == ["recalculate_simulated_standings"]
