"""Canonical real/simulated standings and post-match forecast evaluation."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from prem_engine_api.api.forecasts import ClubResponse
from prem_engine_api.db.dependencies import get_db_session
from prem_engine_api.domain.enums import FixtureStatus, PredictionState, ResultKind
from prem_engine_api.domain.models import (
    ActualResultRevision,
    Club,
    Match,
    PredictionVersion,
    Season,
    SeasonClub,
    StoredSimulation,
)
from prem_engine_api.domain.product_evaluation import (
    EVALUATION_CALCULATION_VERSION,
    AggregateEvaluation,
    ForecastEvaluationInput,
    aggregate_evaluations,
)
from prem_engine_api.domain.standings import (
    STANDINGS_CALCULATION_VERSION,
    CalculatedStandingsRow,
    MatchScore,
    calculate_standings,
)

router = APIRouter(prefix="/api", tags=["standings", "evaluation"])


class SeasonResponse(BaseModel):
    season_uuid: UUID
    label: str
    start_date: date
    end_date: date


class StandingsRowResponse(BaseModel):
    position: int
    club: ClubResponse
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int


class StandingsTableResponse(BaseModel):
    kind: Literal["real", "simulated"]
    calculation_version: str
    source_fixture_count: int
    rows: list[StandingsRowResponse]


class FairComparisonResponse(BaseModel):
    source_fixture_count: int
    real_rows: list[StandingsRowResponse]
    simulated_rows: list[StandingsRowResponse]


class StandingsOverviewResponse(BaseModel):
    season: SeasonResponse | None
    calculated_at: datetime
    real: StandingsTableResponse
    simulated: StandingsTableResponse
    fair_comparison: FairComparisonResponse


class EvaluationMetricsResponse(BaseModel):
    calculation_version: str
    sample_count: int
    excluded_count: int
    outcome_accuracy: float | None
    simulation_outcome_accuracy: float | None
    exact_simulated_score_accuracy: float | None
    log_loss: float | None
    brier_score: float | None
    ranked_probability_score: float | None
    expected_goal_mae: float | None
    expected_calibration_error: float | None


class MatchEvaluationResponse(BaseModel):
    match_uuid: UUID
    kickoff_at: datetime
    home: ClubResponse
    away: ClubResponse
    model_version: str
    home_win_probability: Decimal
    draw_probability: Decimal
    away_win_probability: Decimal
    expected_home_goals: Decimal
    expected_away_goals: Decimal
    simulated_home_goals: int
    simulated_away_goals: int
    actual_home_goals: int
    actual_away_goals: int
    actual_outcome: Literal["home", "draw", "away"]
    forecast_outcome: Literal["home", "draw", "away"]
    simulation_outcome: Literal["home", "draw", "away"]
    forecast_outcome_correct: bool
    simulation_outcome_correct: bool
    exact_simulated_score_correct: bool
    result_kind: str
    included_in_aggregate: bool


class EvaluationOverviewResponse(BaseModel):
    season: SeasonResponse | None
    calculated_at: datetime
    paired_fixture_count: int
    metrics: EvaluationMetricsResponse
    matches: list[MatchEvaluationResponse]


def _season_response(season: Season | None) -> SeasonResponse | None:
    if season is None:
        return None
    return SeasonResponse(
        season_uuid=season.season_uuid,
        label=season.label,
        start_date=season.start_date,
        end_date=season.end_date,
    )


async def _resolve_season(
    session: AsyncSession, *, season_uuid: UUID | None, today: date
) -> Season | None:
    if season_uuid is not None:
        season: Season | None = await session.get(Season, season_uuid)
        if season is None:
            raise HTTPException(status_code=404, detail="season not found")
        return season
    current: Season | None = await session.scalar(
        select(Season)
        .where(Season.start_date <= today, Season.end_date >= today)
        .order_by(Season.start_date.desc())
        .limit(1)
    )
    if current is not None:
        return current
    latest: Season | None = await session.scalar(
        select(Season).order_by(Season.start_date.desc()).limit(1)
    )
    return latest


def _club_response(club: Club) -> ClubResponse:
    return ClubResponse(
        club_uuid=club.club_uuid,
        name=club.canonical_name,
        short_name=club.short_name,
        crest_url=club.crest_url,
    )


def _standings_rows(
    rows: tuple[CalculatedStandingsRow, ...], clubs: dict[UUID, Club]
) -> list[StandingsRowResponse]:
    return [
        StandingsRowResponse(
            position=row.position,
            club=_club_response(clubs[row.club_uuid]),
            played=row.played,
            won=row.won,
            drawn=row.drawn,
            lost=row.lost,
            goals_for=row.goals_for,
            goals_against=row.goals_against,
            goal_difference=row.goal_difference,
            points=row.points,
        )
        for row in rows
    ]


def _empty_standings(*, now: datetime) -> StandingsOverviewResponse:
    real = StandingsTableResponse(
        kind="real",
        calculation_version=STANDINGS_CALCULATION_VERSION,
        source_fixture_count=0,
        rows=[],
    )
    simulated = StandingsTableResponse(
        kind="simulated",
        calculation_version=STANDINGS_CALCULATION_VERSION,
        source_fixture_count=0,
        rows=[],
    )
    return StandingsOverviewResponse(
        season=None,
        calculated_at=now,
        real=real,
        simulated=simulated,
        fair_comparison=FairComparisonResponse(
            source_fixture_count=0, real_rows=[], simulated_rows=[]
        ),
    )


async def build_standings_overview(
    session: AsyncSession,
    *,
    season_uuid: UUID | None = None,
    now: datetime,
) -> StandingsOverviewResponse:
    season = await _resolve_season(session, season_uuid=season_uuid, today=now.date())
    if season is None:
        return _empty_standings(now=now)

    matches = list(
        await session.scalars(
            select(Match).where(Match.season_uuid == season.season_uuid)
        )
    )
    club_ids = set(
        await session.scalars(
            select(SeasonClub.club_uuid).where(SeasonClub.season_uuid == season.season_uuid)
        )
    )
    for match in matches:
        club_ids.update((match.home_club_uuid, match.away_club_uuid))
    clubs = {
        club.club_uuid: club
        for club in (
            list(await session.scalars(select(Club).where(Club.club_uuid.in_(club_ids))))
            if club_ids
            else []
        )
    }
    club_names = {club_uuid: club.canonical_name for club_uuid, club in clubs.items()}

    real_records = (
        await session.execute(
            select(Match, ActualResultRevision)
            .join(ActualResultRevision, ActualResultRevision.match_uuid == Match.match_uuid)
            .where(
                Match.season_uuid == season.season_uuid,
                Match.status.in_(
                    (FixtureStatus.FINISHED, FixtureStatus.ABANDONED, FixtureStatus.AWARDED)
                ),
                ActualResultRevision.accepted.is_(True),
            )
        )
    ).all()
    real_scores = {
        match.match_uuid: MatchScore(
            match_uuid=match.match_uuid,
            home_club_uuid=match.home_club_uuid,
            away_club_uuid=match.away_club_uuid,
            home_goals=result.home_goals,
            away_goals=result.away_goals,
        )
        for match, result in real_records
    }

    simulation_records = (
        await session.execute(
            select(Match, StoredSimulation)
            .join(PredictionVersion, PredictionVersion.match_uuid == Match.match_uuid)
            .join(
                StoredSimulation,
                StoredSimulation.prediction_version_uuid
                == PredictionVersion.prediction_version_uuid,
            )
            .where(
                Match.season_uuid == season.season_uuid,
                PredictionVersion.state.in_(
                    (PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)
                ),
            )
        )
    ).all()
    simulated_scores = {
        match.match_uuid: MatchScore(
            match_uuid=match.match_uuid,
            home_club_uuid=match.home_club_uuid,
            away_club_uuid=match.away_club_uuid,
            home_goals=simulation.home_goals,
            away_goals=simulation.away_goals,
        )
        for match, simulation in simulation_records
        if now
        >= simulation.presentation_started_at
        + timedelta(seconds=simulation.presentation_duration_seconds)
    }
    fair_match_ids = real_scores.keys() & simulated_scores.keys()
    real_rows = calculate_standings(club_names, real_scores.values())
    simulated_rows = calculate_standings(club_names, simulated_scores.values())
    fair_real_rows = calculate_standings(
        club_names, (real_scores[match_uuid] for match_uuid in fair_match_ids)
    )
    fair_simulated_rows = calculate_standings(
        club_names, (simulated_scores[match_uuid] for match_uuid in fair_match_ids)
    )
    return StandingsOverviewResponse(
        season=_season_response(season),
        calculated_at=now,
        real=StandingsTableResponse(
            kind="real",
            calculation_version=STANDINGS_CALCULATION_VERSION,
            source_fixture_count=len(real_scores),
            rows=_standings_rows(real_rows, clubs),
        ),
        simulated=StandingsTableResponse(
            kind="simulated",
            calculation_version=STANDINGS_CALCULATION_VERSION,
            source_fixture_count=len(simulated_scores),
            rows=_standings_rows(simulated_rows, clubs),
        ),
        fair_comparison=FairComparisonResponse(
            source_fixture_count=len(fair_match_ids),
            real_rows=_standings_rows(fair_real_rows, clubs),
            simulated_rows=_standings_rows(fair_simulated_rows, clubs),
        ),
    )


def _empty_metrics() -> EvaluationMetricsResponse:
    return EvaluationMetricsResponse(
        calculation_version=EVALUATION_CALCULATION_VERSION,
        sample_count=0,
        excluded_count=0,
        outcome_accuracy=None,
        simulation_outcome_accuracy=None,
        exact_simulated_score_accuracy=None,
        log_loss=None,
        brier_score=None,
        ranked_probability_score=None,
        expected_goal_mae=None,
        expected_calibration_error=None,
    )


def _metrics_response(metrics: AggregateEvaluation) -> EvaluationMetricsResponse:
    return EvaluationMetricsResponse(
        calculation_version=EVALUATION_CALCULATION_VERSION,
        **metrics.__dict__,
    )


async def build_evaluation_overview(
    session: AsyncSession,
    *,
    season_uuid: UUID | None = None,
    now: datetime,
) -> EvaluationOverviewResponse:
    season = await _resolve_season(session, season_uuid=season_uuid, today=now.date())
    if season is None:
        return EvaluationOverviewResponse(
            season=None,
            calculated_at=now,
            paired_fixture_count=0,
            metrics=_empty_metrics(),
            matches=[],
        )

    home_club = aliased(Club)
    away_club = aliased(Club)
    records = (
        await session.execute(
            select(
                Match,
                home_club,
                away_club,
                PredictionVersion,
                StoredSimulation,
                ActualResultRevision,
            )
            .join(home_club, home_club.club_uuid == Match.home_club_uuid)
            .join(away_club, away_club.club_uuid == Match.away_club_uuid)
            .join(PredictionVersion, PredictionVersion.match_uuid == Match.match_uuid)
            .join(
                StoredSimulation,
                StoredSimulation.prediction_version_uuid
                == PredictionVersion.prediction_version_uuid,
            )
            .join(ActualResultRevision, ActualResultRevision.match_uuid == Match.match_uuid)
            .where(
                Match.season_uuid == season.season_uuid,
                PredictionVersion.state.in_(
                    (PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)
                ),
                ActualResultRevision.accepted.is_(True),
                Match.status.in_(
                    (FixtureStatus.FINISHED, FixtureStatus.ABANDONED, FixtureStatus.AWARDED)
                ),
            )
            .order_by(Match.current_kickoff_at.desc(), Match.match_uuid)
        )
    ).all()
    inputs = tuple(
        ForecastEvaluationInput(
            match_uuid=match.match_uuid,
            home_probability=float(prediction.home_win_probability),
            draw_probability=float(prediction.draw_probability),
            away_probability=float(prediction.away_win_probability),
            expected_home_goals=float(prediction.expected_home_goals),
            expected_away_goals=float(prediction.expected_away_goals),
            simulated_home_goals=simulation.home_goals,
            simulated_away_goals=simulation.away_goals,
            actual_home_goals=result.home_goals,
            actual_away_goals=result.away_goals,
            excluded_from_aggregate=result.result_kind is ResultKind.AWARDED,
        )
        for match, _, _, prediction, simulation, result in records
    )
    metrics, evaluated = aggregate_evaluations(inputs)
    evaluated_by_match = {item.match_uuid: item for item in evaluated}
    matches = []
    for match, home, away, prediction, simulation, result in records:
        item = evaluated_by_match[match.match_uuid]
        matches.append(
            MatchEvaluationResponse(
                match_uuid=match.match_uuid,
                kickoff_at=match.current_kickoff_at,
                home=_club_response(home),
                away=_club_response(away),
                model_version=prediction.model_version,
                home_win_probability=prediction.home_win_probability,
                draw_probability=prediction.draw_probability,
                away_win_probability=prediction.away_win_probability,
                expected_home_goals=prediction.expected_home_goals,
                expected_away_goals=prediction.expected_away_goals,
                simulated_home_goals=simulation.home_goals,
                simulated_away_goals=simulation.away_goals,
                actual_home_goals=result.home_goals,
                actual_away_goals=result.away_goals,
                actual_outcome=item.actual_outcome,
                forecast_outcome=item.forecast_outcome,
                simulation_outcome=item.simulation_outcome,
                forecast_outcome_correct=item.forecast_outcome_correct,
                simulation_outcome_correct=item.simulation_outcome_correct,
                exact_simulated_score_correct=item.exact_simulated_score_correct,
                result_kind=result.result_kind.value,
                included_in_aggregate=not item.excluded_from_aggregate,
            )
        )
    return EvaluationOverviewResponse(
        season=_season_response(season),
        calculated_at=now,
        paired_fixture_count=len(records),
        metrics=_metrics_response(metrics),
        matches=matches,
    )


@router.get("/standings", response_model=StandingsOverviewResponse)
async def standings(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    season_uuid: Annotated[UUID | None, Query()] = None,
) -> StandingsOverviewResponse:
    return await build_standings_overview(
        session, season_uuid=season_uuid, now=datetime.now(UTC)
    )


@router.get("/evaluation", response_model=EvaluationOverviewResponse)
async def evaluation(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    season_uuid: Annotated[UUID | None, Query()] = None,
) -> EvaluationOverviewResponse:
    return await build_evaluation_overview(
        session, season_uuid=season_uuid, now=datetime.now(UTC)
    )
