"""Phase 16B standings and post-match evaluation contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from prem_engine_api.api.insights import (
    build_evaluation_overview,
    build_standings_overview,
)
from prem_engine_api.domain.enums import FixtureStatus, PredictionState, ResultKind
from prem_engine_api.domain.models import (
    ActualResultRevision,
    Club,
    Competition,
    Match,
    PredictionVersion,
    Season,
    SeasonClub,
    StoredSimulation,
)
from prem_engine_api.domain.product_evaluation import (
    ForecastEvaluationInput,
    aggregate_evaluations,
)
from prem_engine_api.domain.standings import MatchScore, calculate_standings
from sqlalchemy.ext.asyncio import AsyncSession


def test_standings_apply_points_and_official_ordering() -> None:
    alpha, bravo, charlie = uuid4(), uuid4(), uuid4()
    rows = calculate_standings(
        {alpha: "Alpha", bravo: "Bravo", charlie: "Charlie"},
        (
            MatchScore(uuid4(), alpha, bravo, 2, 0),
            MatchScore(uuid4(), charlie, alpha, 1, 1),
            MatchScore(uuid4(), bravo, charlie, 3, 0),
        ),
    )

    assert [row.club_uuid for row in rows] == [alpha, bravo, charlie]
    assert [(row.points, row.goal_difference) for row in rows] == [(4, 2), (3, 1), (1, -3)]
    assert all(row.won + row.drawn + row.lost == row.played for row in rows)


def test_evaluation_uses_probability_metrics_and_excludes_awards() -> None:
    ordinary = ForecastEvaluationInput(
        match_uuid=uuid4(),
        home_probability=0.6,
        draw_probability=0.25,
        away_probability=0.15,
        expected_home_goals=1.5,
        expected_away_goals=0.8,
        simulated_home_goals=2,
        simulated_away_goals=0,
        actual_home_goals=2,
        actual_away_goals=0,
    )
    awarded = ForecastEvaluationInput(
        match_uuid=uuid4(),
        home_probability=0.2,
        draw_probability=0.3,
        away_probability=0.5,
        expected_home_goals=0.9,
        expected_away_goals=1.2,
        simulated_home_goals=0,
        simulated_away_goals=1,
        actual_home_goals=3,
        actual_away_goals=0,
        excluded_from_aggregate=True,
    )

    metrics, evaluated = aggregate_evaluations((ordinary, awarded))

    assert metrics.sample_count == 1
    assert metrics.excluded_count == 1
    assert metrics.outcome_accuracy == 1.0
    assert metrics.simulation_outcome_accuracy == 1.0
    assert metrics.exact_simulated_score_accuracy == 1.0
    assert metrics.log_loss == pytest.approx(0.5108256238)
    assert evaluated[1].excluded_from_aggregate is True


async def _prediction(
    session: AsyncSession,
    *,
    match: Match,
    start: datetime,
    simulated_score: tuple[int, int],
) -> PredictionVersion:
    prediction = PredictionVersion(
        match_uuid=match.match_uuid,
        version_number=1,
        state=PredictionState.GENERATING,
        feature_cutoff_at=match.prediction_due_at,
        model_version="goals-v1-test",
        feature_snapshot_checksum="a" * 64,
        home_win_probability=Decimal("0.60000000"),
        draw_probability=Decimal("0.25000000"),
        away_win_probability=Decimal("0.15000000"),
        expected_home_goals=Decimal("1.5000"),
        expected_away_goals=Decimal("0.8000"),
        statistics_distribution={},
        locked_at=None,
    )
    session.add(prediction)
    await session.flush()
    session.add(
        StoredSimulation(
            prediction_version_uuid=prediction.prediction_version_uuid,
            random_seed=7,
            home_goals=simulated_score[0],
            away_goals=simulated_score[1],
            statistics={},
            events=[],
            checksum="b" * 64,
            presentation_started_at=start,
            presentation_duration_seconds=60,
        )
    )
    await session.flush()
    prediction.state = PredictionState.ACTIVE_LOCKED
    prediction.locked_at = match.prediction_due_at
    await session.flush()
    return prediction


@pytest.mark.asyncio
async def test_product_overviews_keep_timelines_separate(db_session: AsyncSession) -> None:
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    competition = Competition(slug="phase-16b", name="Premier League", country_code="GB")
    alpha = Club(canonical_name="Alpha", short_name="ALP")
    bravo = Club(canonical_name="Bravo", short_name="BRA")
    charlie = Club(canonical_name="Charlie", short_name="CHA")
    db_session.add_all((competition, alpha, bravo, charlie))
    await db_session.flush()
    season = Season(
        competition_uuid=competition.competition_uuid,
        label="2026/27",
        start_date=date(2026, 8, 1),
        end_date=date(2027, 5, 31),
    )
    db_session.add(season)
    await db_session.flush()
    db_session.add_all(
        SeasonClub(season_uuid=season.season_uuid, club_uuid=club.club_uuid)
        for club in (alpha, bravo, charlie)
    )
    await db_session.flush()

    finished = Match(
        season_uuid=season.season_uuid,
        home_club_uuid=alpha.club_uuid,
        away_club_uuid=bravo.club_uuid,
        status=FixtureStatus.FINISHED,
        current_kickoff_at=now - timedelta(days=1),
        prediction_due_at=now - timedelta(days=2),
    )
    future_revealed = Match(
        season_uuid=season.season_uuid,
        home_club_uuid=bravo.club_uuid,
        away_club_uuid=charlie.club_uuid,
        status=FixtureStatus.SCHEDULED,
        current_kickoff_at=now + timedelta(hours=23),
        prediction_due_at=now - timedelta(hours=1),
    )
    future_hidden = Match(
        season_uuid=season.season_uuid,
        home_club_uuid=charlie.club_uuid,
        away_club_uuid=alpha.club_uuid,
        status=FixtureStatus.SCHEDULED,
        current_kickoff_at=now + timedelta(hours=24),
        prediction_due_at=now,
    )
    db_session.add_all((finished, future_revealed, future_hidden))
    await db_session.flush()
    await _prediction(
        db_session,
        match=finished,
        start=now - timedelta(days=2),
        simulated_score=(1, 1),
    )
    await _prediction(
        db_session,
        match=future_revealed,
        start=now - timedelta(minutes=2),
        simulated_score=(0, 2),
    )
    await _prediction(
        db_session,
        match=future_hidden,
        start=now,
        simulated_score=(4, 0),
    )
    db_session.add(
        ActualResultRevision(
            match_uuid=finished.match_uuid,
            revision_number=1,
            home_goals=2,
            away_goals=0,
            result_kind=ResultKind.REGULAR,
            accepted=True,
            observed_at=now,
        )
    )
    await db_session.flush()

    standings = await build_standings_overview(db_session, season_uuid=season.season_uuid, now=now)
    evaluation = await build_evaluation_overview(
        db_session, season_uuid=season.season_uuid, now=now
    )

    assert standings.real.source_fixture_count == 1
    assert standings.simulated.source_fixture_count == 2
    assert standings.fair_comparison.source_fixture_count == 1
    assert standings.real.rows[0].club.name == "Alpha"
    assert standings.simulated.rows[0].club.name == "Charlie"
    assert evaluation.paired_fixture_count == 1
    assert evaluation.metrics.sample_count == 1
    assert evaluation.matches[0].actual_home_goals == 2
    assert evaluation.matches[0].simulated_home_goals == 1
