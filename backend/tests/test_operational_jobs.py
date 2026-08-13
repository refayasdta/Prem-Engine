"""Background standings persistence and current player-context ingestion."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import FixtureStatus, JobStatus, PredictionState
from prem_engine_api.domain.models import (
    Club,
    ClubExternalReference,
    Competition,
    JobRun,
    Match,
    MatchExternalReference,
    ObservedLineupPlayer,
    PlayerAvailabilityReport,
    PlayerMatchPerformance,
    PredictionVersion,
    ProviderRequestBudget,
    Season,
    SeasonClub,
    SquadMembership,
    StandingsRow,
    StandingsSnapshot,
    StoredSimulation,
    TransferObservation,
)
from prem_engine_api.ingestion.player_context import PlayerContextIngestor
from prem_engine_api.ingestion.player_sync import _next_cursor
from prem_engine_api.jobs.dispatcher import dispatch_once
from prem_engine_api.jobs.leases import complete_job
from prem_engine_api.jobs.standings import recalculate_simulated_standings
from prem_engine_api.operations.snapshot import collect_operational_snapshot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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


@pytest.mark.asyncio
async def test_operational_snapshot_counts_missed_t24_and_quota_usage(
    db_session: AsyncSession,
) -> None:
    _, _, _, match, now = await _season_and_match(db_session)
    match.status = FixtureStatus.SCHEDULED
    db_session.add_all(
        (
            JobRun(
                idempotency_key="generate:snapshot-test",
                job_type="generate_prediction",
                status=JobStatus.PENDING,
                match_uuid=match.match_uuid,
                due_at=match.prediction_due_at,
                attempt_count=0,
            ),
            ProviderRequestBudget(
                provider="kickoffapi",
                budget_date=now.date(),
                request_count=80,
                operational_limit=85,
                hard_limit=100,
            ),
        )
    )
    await db_session.flush()

    snapshot = await collect_operational_snapshot(
        db_session,
        now=now,
        t24_grace_seconds=600,
    )

    assert snapshot.jobs_pending == 1
    assert snapshot.jobs_leased == 0
    assert snapshot.jobs_running == 0
    assert snapshot.jobs_failed == 0
    assert snapshot.t24_forecasts_missing == 1
    assert snapshot.provider_requests_today == 80


@pytest.mark.asyncio
async def test_standings_job_persists_revealed_snapshot_and_completes(
    db_session: AsyncSession,
) -> None:
    season, home, away, match, now = await _season_and_match(db_session)
    prediction = PredictionVersion(
        match_uuid=match.match_uuid,
        version_number=1,
        state=PredictionState.GENERATING,
        feature_cutoff_at=match.prediction_due_at,
        model_version="test",
        feature_snapshot_checksum="a" * 64,
        home_win_probability=Decimal("0.50000000"),
        draw_probability=Decimal("0.25000000"),
        away_win_probability=Decimal("0.25000000"),
        expected_home_goals=Decimal("1.5000"),
        expected_away_goals=Decimal("0.8000"),
        statistics_distribution={},
        locked_at=now - timedelta(minutes=2),
    )
    db_session.add(prediction)
    await db_session.flush()
    db_session.add(
        StoredSimulation(
            prediction_version_uuid=prediction.prediction_version_uuid,
            random_seed=10,
            home_goals=2,
            away_goals=0,
            statistics={},
            events=[],
            checksum="b" * 64,
            presentation_started_at=now - timedelta(minutes=2),
            presentation_duration_seconds=60,
        )
    )
    await db_session.flush()
    prediction.state = PredictionState.ACTIVE_LOCKED
    job = JobRun(
        idempotency_key="recalculate:test",
        job_type="recalculate_simulated_standings",
        status=JobStatus.RUNNING,
        match_uuid=match.match_uuid,
        due_at=now - timedelta(minutes=1),
        lease_owner="worker",
        lease_expires_at=now + timedelta(minutes=5),
        attempt_count=1,
        started_at=now - timedelta(seconds=10),
    )
    db_session.add(job)
    await db_session.flush()

    outcome = await recalculate_simulated_standings(
        db_session, match_uuid=match.match_uuid, as_of=now
    )
    await complete_job(db_session, job_uuid=job.job_uuid, worker_id="worker", now=now)

    assert outcome.season_uuid == season.season_uuid
    assert outcome.source_fixture_count == 1
    assert outcome.row_count == 2
    rows = list(
        await db_session.scalars(
            select(StandingsRow)
            .where(StandingsRow.snapshot_uuid == outcome.snapshot_uuid)
            .order_by(StandingsRow.position)
        )
    )
    assert [(row.club_uuid, row.points) for row in rows] == [
        (home.club_uuid, 3),
        (away.club_uuid, 0),
    ]
    snapshot = await db_session.get(StandingsSnapshot, outcome.snapshot_uuid)
    assert snapshot is not None and snapshot.source_fixture_count == 1
    assert job.status is JobStatus.SUCCEEDED
    assert job.lease_owner is None


@pytest.mark.asyncio
async def test_dispatcher_consumes_simulated_standings_jobs(
    db_session: AsyncSession,
) -> None:
    _, _, _, match, _ = await _season_and_match(db_session)
    now = datetime.now(UTC)
    prediction = PredictionVersion(
        match_uuid=match.match_uuid,
        version_number=1,
        state=PredictionState.GENERATING,
        feature_cutoff_at=match.prediction_due_at,
        model_version="test",
        feature_snapshot_checksum="c" * 64,
        home_win_probability=Decimal("0.40000000"),
        draw_probability=Decimal("0.30000000"),
        away_win_probability=Decimal("0.30000000"),
        expected_home_goals=Decimal("1.2000"),
        expected_away_goals=Decimal("1.0000"),
        statistics_distribution={},
        locked_at=now - timedelta(minutes=2),
    )
    db_session.add(prediction)
    await db_session.flush()
    db_session.add(
        StoredSimulation(
            prediction_version_uuid=prediction.prediction_version_uuid,
            random_seed=11,
            home_goals=1,
            away_goals=1,
            statistics={},
            events=[],
            checksum="d" * 64,
            presentation_started_at=now - timedelta(minutes=2),
            presentation_duration_seconds=60,
        )
    )
    await db_session.flush()
    prediction.state = PredictionState.ACTIVE_LOCKED
    job = JobRun(
        idempotency_key="recalculate:dispatcher-test",
        job_type="recalculate_simulated_standings",
        status=JobStatus.PENDING,
        match_uuid=match.match_uuid,
        due_at=now - timedelta(seconds=1),
        attempt_count=0,
    )
    db_session.add(job)
    await db_session.flush()
    connection = await db_session.connection()
    sessions = async_sessionmaker(bind=connection, expire_on_commit=False)

    summary = await dispatch_once(
        sessions,
        settings=Settings(),
        worker_id="standings-worker",
        now=now,
    )

    assert summary.jobs_claimed == 1
    assert summary.standings_recalculated == 1
    assert summary.forecasts_created == 0
    async with sessions() as session:
        completed = await session.get(JobRun, job.job_uuid)
        assert completed is not None and completed.status is JobStatus.SUCCEEDED
        assert await session.scalar(select(func.count()).select_from(StandingsSnapshot)) == 1


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
                }
            ]
        },
        observed_at=now,
        provider_payload_key="raw-2",
    )
    assert transfer.created == 1

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
