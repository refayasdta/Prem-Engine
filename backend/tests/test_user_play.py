"""Stage 4 per-device Play-window acceptance tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from prem_engine_api.api.insights import (
    build_evaluation_overview,
    build_standings_overview,
)
from prem_engine_api.config import Settings
from prem_engine_api.db.base import Base
from prem_engine_api.domain.enums import FixtureStatus
from prem_engine_api.domain.lifecycle import reschedule_match
from prem_engine_api.domain.models import (
    ActualResultRevision,
    Club,
    Competition,
    DeviceSimulation,
    FixtureScheduleRevision,
    LocalWorkerState,
    Match,
    Season,
    SeasonClub,
)
from prem_engine_api.forecasting.contracts import (
    FeatureSnapshotInput,
    ForecastPackage,
    LineupPlayer,
    ModelForecast,
    TeamLineup,
)
from prem_engine_api.forecasting.user_play import UserPlayError, play_device_simulation
from prem_engine_modeling.goals import forecast_from_rates
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


async def _seed_match(session: AsyncSession) -> tuple[Match, Club, Club, datetime]:
    competition = Competition(slug=f"play-{uuid4()}", name="Premier League", country_code="GB")
    home = Club(canonical_name=f"Home {uuid4()}", short_name="HOM")
    away = Club(canonical_name=f"Away {uuid4()}", short_name="AWY")
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
        )
    )
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
    session.add_all(
        (
            FixtureScheduleRevision(
                match_uuid=match.match_uuid,
                revision_number=1,
                kickoff_at=kickoff,
                canonical_status=FixtureStatus.SCHEDULED,
                provider_status="NS",
                observed_at=datetime(2026, 8, 1, tzinfo=UTC),
            ),
            LocalWorkerState(
                singleton_key=1,
                status="idle",
                last_fixture_success_at=kickoff,
            ),
        )
    )
    await session.flush()
    return match, home, away, kickoff


def _lineup(club: Club, prefix: str) -> TeamLineup:
    positions = ("GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "FWD", "FWD", "FWD")

    def player(index: int, position: str, *, substitute: bool = False) -> LineupPlayer:
        return LineupPlayer(
            player_uuid=uuid4(),
            name=f"{prefix} {index}",
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
        confidence=0.8,
    )


def _package(match: Match, home: Club, away: Club) -> ForecastPackage:
    cutoff = match.prediction_due_at
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
            schema_version="play-test-v1",
            feature_cutoff_at=cutoff,
            latest_source_observed_at=cutoff - timedelta(minutes=1),
            payload={"outcome_model": {"sha256": "a" * 64}},
        ),
        forecast=ModelForecast(
            outcome_model_version="goals-play-test",
            statistics_model_version="statistics-play-test",
            expected_home_goals=1.6,
            expected_away_goals=1.2,
            score_matrix=goals.score_matrix,
            statistic_means=means,
            statistic_intervals_90={key: (0.0, value + 3.0) for key, value in means.items()},
        ),
        home_lineup=_lineup(home, "Home"),
        away_lineup=_lineup(away, "Away"),
        random_seed=1,
    )


class FixedFactory:
    def __init__(self, package: ForecastPackage) -> None:
        self.package = package
        self.calls = 0

    async def build(
        self, session: AsyncSession, *, match_uuid: UUID, cutoff: datetime
    ) -> ForecastPackage:
        del session
        assert match_uuid == self.package.match_uuid
        assert cutoff == self.package.feature_snapshot.feature_cutoff_at
        self.calls += 1
        return self.package


def _settings() -> Settings:
    return Settings(
        deployment_mode="local",
        local_fixture_freshness_seconds=14_400,
        simulation_presentation_seconds=60,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offset", "accepted"),
    (
        (timedelta(hours=-24, seconds=-1), False),
        (timedelta(hours=-24), True),
        (timedelta(hours=-12), True),
        (timedelta(), True),
        (timedelta(minutes=45), True),
        (timedelta(minutes=45, seconds=1), False),
    ),
)
async def test_play_window_is_inclusive_at_both_boundaries(
    db_session: AsyncSession, offset: timedelta, accepted: bool
) -> None:
    match, home, away, kickoff = await _seed_match(db_session)
    factory = FixedFactory(_package(match, home, away))
    device_uuid = uuid4()
    now = kickoff + offset

    if accepted:
        outcome = await play_device_simulation(
            db_session,
            match_uuid=match.match_uuid,
            device_uuid=device_uuid,
            settings=_settings(),
            now=now,
            forecast_factory=factory,
        )
        assert outcome.created
        assert outcome.simulation.play_classification == (
            "pre_kickoff_user_simulation" if now < kickoff else "in_play_user_simulation"
        )
    else:
        with pytest.raises(UserPlayError) as captured:
            await play_device_simulation(
                db_session,
                match_uuid=match.match_uuid,
                device_uuid=device_uuid,
                settings=_settings(),
                now=now,
                forecast_factory=factory,
            )
        assert captured.value.code in ("play_window_locked", "play_window_missed")
        if now > kickoff + timedelta(minutes=45):
            missed = await db_session.scalar(
                select(DeviceSimulation).where(DeviceSimulation.device_uuid == device_uuid)
            )
            assert missed is not None and missed.state == "missed"


@pytest.mark.asyncio
async def test_repeated_play_returns_one_stored_simulation(db_session: AsyncSession) -> None:
    match, home, away, kickoff = await _seed_match(db_session)
    factory = FixedFactory(_package(match, home, away))
    device_uuid = uuid4()
    first = await play_device_simulation(
        db_session,
        match_uuid=match.match_uuid,
        device_uuid=device_uuid,
        settings=_settings(),
        now=kickoff - timedelta(hours=1),
        forecast_factory=factory,
    )
    second = await play_device_simulation(
        db_session,
        match_uuid=match.match_uuid,
        device_uuid=device_uuid,
        settings=_settings(),
        now=kickoff + timedelta(minutes=20),
        forecast_factory=factory,
    )

    assert first.simulation.device_simulation_uuid == second.simulation.device_simulation_uuid
    assert first.simulation.simulation_checksum == second.simulation.simulation_checksum
    assert not second.created
    assert factory.calls == 1
    count = await db_session.scalar(select(func.count(DeviceSimulation.device_simulation_uuid)))
    assert int(count or 0) == 1


@pytest.mark.asyncio
async def test_two_devices_receive_distinct_stable_timelines(db_session: AsyncSession) -> None:
    match, home, away, kickoff = await _seed_match(db_session)
    factory = FixedFactory(_package(match, home, away))
    first = await play_device_simulation(
        db_session,
        match_uuid=match.match_uuid,
        device_uuid=uuid4(),
        settings=_settings(),
        now=kickoff,
        forecast_factory=factory,
    )
    second = await play_device_simulation(
        db_session,
        match_uuid=match.match_uuid,
        device_uuid=uuid4(),
        settings=_settings(),
        now=kickoff,
        forecast_factory=factory,
    )

    assert first.simulation.random_seed != second.simulation.random_seed
    assert first.simulation.simulation_checksum != second.simulation.simulation_checksum
    count = await db_session.scalar(select(func.count(DeviceSimulation.device_simulation_uuid)))
    assert int(count or 0) == 2


@pytest.mark.asyncio
async def test_stale_fixture_data_disables_new_play(db_session: AsyncSession) -> None:
    match, home, away, kickoff = await _seed_match(db_session)
    worker = await db_session.scalar(
        select(LocalWorkerState).where(LocalWorkerState.singleton_key == 1)
    )
    assert worker is not None
    worker.last_fixture_success_at = kickoff - timedelta(hours=5)
    with pytest.raises(UserPlayError, match="stale") as captured:
        await play_device_simulation(
            db_session,
            match_uuid=match.match_uuid,
            device_uuid=uuid4(),
            settings=_settings(),
            now=kickoff,
            forecast_factory=FixedFactory(_package(match, home, away)),
        )
    assert captured.value.code == "fixture_data_stale"


@pytest.mark.asyncio
async def test_reschedule_voids_old_timeline_and_opens_new_revision(
    db_session: AsyncSession,
) -> None:
    match, home, away, kickoff = await _seed_match(db_session)
    device_uuid = uuid4()
    played = await play_device_simulation(
        db_session,
        match_uuid=match.match_uuid,
        device_uuid=device_uuid,
        settings=_settings(),
        now=kickoff,
        forecast_factory=FixedFactory(_package(match, home, away)),
    )
    revised_kickoff = kickoff + timedelta(days=7)
    result = await reschedule_match(
        db_session,
        match_uuid=match.match_uuid,
        revised_kickoff_at=revised_kickoff,
        provider_status="NS",
        actor="test",
        observed_at=kickoff + timedelta(hours=1),
    )

    assert played.simulation.state == "void"
    assert played.simulation.void_reason == "fixture_rescheduled"
    assert result.revision_uuid != played.simulation.schedule_revision_uuid
    current = await db_session.scalar(
        select(FixtureScheduleRevision).where(
            FixtureScheduleRevision.revision_uuid == result.revision_uuid
        )
    )
    assert current is not None and current.kickoff_at == revised_kickoff


@pytest.mark.asyncio
async def test_device_standings_count_one_play_exactly_once(db_session: AsyncSession) -> None:
    match, home, away, kickoff = await _seed_match(db_session)
    device_uuid = uuid4()
    factory = FixedFactory(_package(match, home, away))
    await play_device_simulation(
        db_session,
        match_uuid=match.match_uuid,
        device_uuid=device_uuid,
        settings=_settings(),
        now=kickoff,
        forecast_factory=factory,
    )
    await play_device_simulation(
        db_session,
        match_uuid=match.match_uuid,
        device_uuid=device_uuid,
        settings=_settings(),
        now=kickoff + timedelta(minutes=1),
        forecast_factory=factory,
    )
    standings = await build_standings_overview(
        db_session,
        season_uuid=match.season_uuid,
        device_uuid=device_uuid,
        now=kickoff + timedelta(minutes=1),
    )

    assert standings.simulated.source_fixture_count == 1
    assert standings.coverage.played == 1
    assert standings.coverage.eligible == 1
    assert sum(row.played for row in standings.simulated.rows) == 2


@pytest.mark.asyncio
async def test_device_evaluation_uses_its_own_saved_play(db_session: AsyncSession) -> None:
    match, home, away, kickoff = await _seed_match(db_session)
    device_uuid = uuid4()
    await play_device_simulation(
        db_session,
        match_uuid=match.match_uuid,
        device_uuid=device_uuid,
        settings=_settings(),
        now=kickoff,
        forecast_factory=FixedFactory(_package(match, home, away)),
    )
    match.status = FixtureStatus.FINISHED
    db_session.add(
        ActualResultRevision(
            match_uuid=match.match_uuid,
            revision_number=1,
            home_goals=2,
            away_goals=1,
            accepted=True,
            provider_payload_key="test/result",
            observed_at=kickoff + timedelta(hours=2),
        )
    )
    await db_session.flush()
    evaluation = await build_evaluation_overview(
        db_session,
        season_uuid=match.season_uuid,
        device_uuid=device_uuid,
        now=kickoff + timedelta(hours=3),
    )

    assert evaluation.paired_fixture_count == 1
    assert evaluation.metrics.sample_count == 1
    assert evaluation.matches[0].match_uuid == match.match_uuid


@pytest.mark.asyncio
async def test_concurrent_play_requests_share_one_committed_timeline() -> None:
    import os

    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("concurrency test requires an explicitly isolated TEST_DATABASE_URL")
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))
        async with sessions() as seed_session:
            match, home, away, kickoff = await _seed_match(seed_session)
            package = _package(match, home, away)
            match_uuid = match.match_uuid
            await seed_session.commit()
        device_uuid = uuid4()

        async def invoke() -> tuple[UUID, bool]:
            async with sessions() as session:
                outcome = await play_device_simulation(
                    session,
                    match_uuid=match_uuid,
                    device_uuid=device_uuid,
                    settings=_settings(),
                    now=kickoff,
                    forecast_factory=FixedFactory(package),
                )
                await session.commit()
                return outcome.simulation.device_simulation_uuid, outcome.created

        first, second = await asyncio.gather(invoke(), invoke())
        assert first[0] == second[0]
        assert sorted((first[1], second[1])) == [False, True]
        async with sessions() as check_session:
            count = await check_session.scalar(
                select(func.count(DeviceSimulation.device_simulation_uuid))
            )
            assert int(count or 0) == 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))
        await engine.dispose()
