"""Public match forecast, countdown, and synchronized replay endpoint."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from prem_engine_api.db.dependencies import get_db_session
from prem_engine_api.domain.enums import FixtureStatus, JobStatus, PredictionState
from prem_engine_api.domain.models import (
    Club,
    JobRun,
    Match,
    PredictedLineup,
    PredictionVersion,
    StoredSimulation,
)
from prem_engine_api.forecasting.presentation import event_is_visible, presentation_clock

router = APIRouter(prefix="/api/matches", tags=["forecasts"])


class ClubResponse(BaseModel):
    club_uuid: UUID
    name: str
    short_name: str
    crest_url: str | None


class PresentationResponse(BaseModel):
    started_at: datetime | None
    duration_seconds: int
    phase: str
    elapsed_seconds: float
    remaining_seconds: int
    football_second: int
    complete: bool


class PredictionResponse(BaseModel):
    prediction_version_uuid: UUID
    version_number: int
    locked_at: datetime
    feature_cutoff_at: datetime
    feature_snapshot_checksum: str
    model_version: str
    expected_home_goals: Decimal
    expected_away_goals: Decimal
    home_win_probability: Decimal
    draw_probability: Decimal
    away_win_probability: Decimal
    statistics_distribution: dict[str, Any]
    expected_lineups: dict[str, Any]


class SimulationResponse(BaseModel):
    simulation_uuid: UUID
    checksum: str
    scoreboard_home: int
    scoreboard_away: int
    events: list[dict[str, Any]]
    visible_statistics: dict[str, int]
    final_score: dict[str, int] | None
    final_statistics: dict[str, Any] | None


class MatchForecastResponse(BaseModel):
    match_uuid: UUID
    fixture_status: str
    lifecycle_state: Literal[
        "countdown",
        "generating",
        "live",
        "complete",
        "postponed",
        "cancelled",
        "unavailable",
    ]
    kickoff_at: datetime
    prediction_due_at: datetime
    seconds_until_generation: int
    home: ClubResponse
    away: ClubResponse
    prediction: PredictionResponse | None
    presentation: PresentationResponse
    simulation: SimulationResponse | None


class UpcomingMatchResponse(BaseModel):
    match_uuid: UUID
    fixture_status: str
    kickoff_at: datetime
    prediction_due_at: datetime
    home: ClubResponse
    away: ClubResponse


async def list_upcoming_match_responses(
    session: AsyncSession, *, now: datetime, limit: int
) -> list[UpcomingMatchResponse]:
    home_club = aliased(Club)
    away_club = aliased(Club)
    rows = (
        await session.execute(
            select(Match, home_club, away_club)
            .join(home_club, home_club.club_uuid == Match.home_club_uuid)
            .join(away_club, away_club.club_uuid == Match.away_club_uuid)
            .where(
                Match.current_kickoff_at >= now,
                Match.status.in_((FixtureStatus.SCHEDULED, FixtureStatus.POSTPONED)),
            )
            .order_by(Match.current_kickoff_at, Match.match_uuid)
            .limit(limit)
        )
    ).all()
    return [
        UpcomingMatchResponse(
            match_uuid=match.match_uuid,
            fixture_status=match.status.value,
            kickoff_at=match.current_kickoff_at,
            prediction_due_at=match.prediction_due_at,
            home=ClubResponse(
                club_uuid=home.club_uuid,
                name=home.canonical_name,
                short_name=home.short_name,
                crest_url=home.crest_url,
            ),
            away=ClubResponse(
                club_uuid=away.club_uuid,
                name=away.canonical_name,
                short_name=away.short_name,
                crest_url=away.crest_url,
            ),
        )
        for match, home, away in rows
    ]


def _visible_statistics(events: list[dict[str, Any]]) -> dict[str, int]:
    output = {
        f"{side}_{name}": 0
        for side in ("home", "away")
        for name in (
            "half_time_goals",
            "shots",
            "shots_on_target",
            "corners",
            "fouls",
            "yellow_cards",
            "red_cards",
        )
    }
    for event in events:
        side = event.get("team")
        event_type = event.get("event_type")
        if side not in ("home", "away"):
            continue
        if event_type == "goal":
            output[f"{side}_shots"] += 1
            output[f"{side}_shots_on_target"] += 1
            if int(event.get("minute", 0)) < 45:
                output[f"{side}_half_time_goals"] += 1
        elif event_type == "shot_on_target":
            output[f"{side}_shots"] += 1
            output[f"{side}_shots_on_target"] += 1
        elif event_type == "shot":
            output[f"{side}_shots"] += 1
        elif event_type in ("corner", "foul", "yellow_card", "red_card"):
            key = {
                "corner": "corners",
                "foul": "fouls",
                "yellow_card": "yellow_cards",
                "red_card": "red_cards",
            }[str(event_type)]
            output[f"{side}_{key}"] += 1
    return output


async def build_match_forecast_response(
    session: AsyncSession, *, match_uuid: UUID, now: datetime
) -> MatchForecastResponse | None:
    home_club = aliased(Club)
    away_club = aliased(Club)
    match_row = (
        await session.execute(
            select(Match, home_club, away_club)
            .join(home_club, home_club.club_uuid == Match.home_club_uuid)
            .join(away_club, away_club.club_uuid == Match.away_club_uuid)
            .where(Match.match_uuid == match_uuid)
        )
    ).one_or_none()
    if match_row is None:
        return None
    match, home, away = match_row
    prediction = await session.scalar(
        select(PredictionVersion).where(
            PredictionVersion.match_uuid == match_uuid,
            PredictionVersion.state.in_((PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)),
        )
    )
    seconds_until = max(0, math.ceil((match.prediction_due_at - now).total_seconds()))
    empty_presentation = PresentationResponse(
        started_at=None,
        duration_seconds=60,
        phase="countdown",
        elapsed_seconds=0.0,
        remaining_seconds=seconds_until,
        football_second=0,
        complete=False,
    )
    common = {
        "match_uuid": match.match_uuid,
        "fixture_status": match.status.value,
        "kickoff_at": match.current_kickoff_at,
        "prediction_due_at": match.prediction_due_at,
        "seconds_until_generation": seconds_until,
        "home": ClubResponse(
            club_uuid=home.club_uuid,
            name=home.canonical_name,
            short_name=home.short_name,
            crest_url=home.crest_url,
        ),
        "away": ClubResponse(
            club_uuid=away.club_uuid,
            name=away.canonical_name,
            short_name=away.short_name,
            crest_url=away.crest_url,
        ),
    }
    if prediction is None:
        if match.status is FixtureStatus.POSTPONED:
            lifecycle = "postponed"
        elif match.status is FixtureStatus.CANCELLED:
            lifecycle = "cancelled"
        else:
            latest_job = await session.scalar(
                select(JobRun)
                .where(
                    JobRun.match_uuid == match_uuid,
                    JobRun.job_type == "generate_prediction",
                )
                .order_by(JobRun.created_at.desc())
                .limit(1)
            )
            if latest_job is not None and latest_job.status is JobStatus.FAILED:
                lifecycle = "unavailable"
            elif now >= match.prediction_due_at:
                lifecycle = "generating"
            else:
                lifecycle = "countdown"
        return MatchForecastResponse(
            **common,
            lifecycle_state=lifecycle,
            prediction=None,
            presentation=empty_presentation,
            simulation=None,
        )

    lineup = await session.scalar(
        select(PredictedLineup).where(
            PredictedLineup.prediction_version_uuid == prediction.prediction_version_uuid
        )
    )
    simulation = await session.scalar(
        select(StoredSimulation).where(
            StoredSimulation.prediction_version_uuid == prediction.prediction_version_uuid
        )
    )
    if lineup is None or simulation is None or prediction.locked_at is None:
        return MatchForecastResponse(
            **common,
            lifecycle_state="unavailable",
            prediction=None,
            presentation=empty_presentation,
            simulation=None,
        )
    clock = presentation_clock(
        started_at=simulation.presentation_started_at,
        duration_seconds=simulation.presentation_duration_seconds,
        now=now,
    )
    visible_events = [event for event in simulation.events if event_is_visible(event, clock)]
    score_home = int(visible_events[-1].get("home_score", 0)) if visible_events else 0
    score_away = int(visible_events[-1].get("away_score", 0)) if visible_events else 0
    presentation = PresentationResponse(
        started_at=simulation.presentation_started_at,
        duration_seconds=simulation.presentation_duration_seconds,
        phase=clock.phase,
        elapsed_seconds=clock.elapsed_seconds,
        remaining_seconds=clock.remaining_seconds,
        football_second=clock.football_second,
        complete=clock.complete,
    )
    return MatchForecastResponse(
        **common,
        lifecycle_state="complete" if clock.complete else "live",
        prediction=PredictionResponse(
            prediction_version_uuid=prediction.prediction_version_uuid,
            version_number=prediction.version_number,
            locked_at=prediction.locked_at,
            feature_cutoff_at=prediction.feature_cutoff_at,
            feature_snapshot_checksum=prediction.feature_snapshot_checksum,
            model_version=prediction.model_version,
            expected_home_goals=prediction.expected_home_goals,
            expected_away_goals=prediction.expected_away_goals,
            home_win_probability=prediction.home_win_probability,
            draw_probability=prediction.draw_probability,
            away_win_probability=prediction.away_win_probability,
            statistics_distribution=prediction.statistics_distribution,
            expected_lineups=lineup.lineup_payload,
        ),
        presentation=presentation,
        simulation=SimulationResponse(
            simulation_uuid=simulation.simulation_uuid,
            checksum=simulation.checksum,
            scoreboard_home=score_home,
            scoreboard_away=score_away,
            events=visible_events,
            visible_statistics=_visible_statistics(visible_events),
            final_score=(
                {"home": simulation.home_goals, "away": simulation.away_goals}
                if clock.complete
                else None
            ),
            final_statistics=simulation.statistics if clock.complete else None,
        ),
    )


@router.get("/upcoming", response_model=list[UpcomingMatchResponse])
async def upcoming_matches(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> list[UpcomingMatchResponse]:
    return await list_upcoming_match_responses(session, now=datetime.now(UTC), limit=limit)


@router.get("/{match_uuid}/forecast", response_model=MatchForecastResponse)
async def match_forecast(
    match_uuid: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MatchForecastResponse:
    response = await build_match_forecast_response(
        session,
        match_uuid=match_uuid,
        now=datetime.now(UTC),
    )
    if response is None:
        raise HTTPException(status_code=404, detail="match not found")
    return response
