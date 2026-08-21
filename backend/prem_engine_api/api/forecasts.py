"""Public match forecast, countdown, and synchronized replay endpoint."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from prem_engine_api.config import get_settings
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
from prem_engine_api.forecasting.lineups import LineupCoverageError
from prem_engine_api.forecasting.presentation import event_is_visible, presentation_clock
from prem_engine_api.forecasting.user_play import (
    UserPlayError,
    load_play_context,
    play_device_simulation,
)

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
    prediction_version_uuid: UUID | None
    version_number: int | None
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
        "locked",
        "available",
        "missed",
        "void",
        "stale",
    ]
    kickoff_at: datetime
    prediction_due_at: datetime
    seconds_until_generation: int
    home: ClubResponse
    away: ClubResponse
    prediction: PredictionResponse | None
    presentation: PresentationResponse
    simulation: SimulationResponse | None
    schedule_revision_uuid: UUID | None = None
    schedule_revision_number: int | None = None
    window_opens_at: datetime | None = None
    window_closes_at: datetime | None = None
    seconds_until_play: int = 0
    data_current: bool = True
    play_classification: str | None = None
    generated_at: datetime | None = None


class PlayRequest(BaseModel):
    device_uuid: UUID


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
                Match.current_kickoff_at >= now - timedelta(minutes=45),
                Match.status.in_(
                    (
                        FixtureStatus.SCHEDULED,
                        FixtureStatus.POSTPONED,
                        FixtureStatus.STARTED,
                        FixtureStatus.SUSPENDED,
                        FixtureStatus.FINISHED,
                        FixtureStatus.ABANDONED,
                        FixtureStatus.AWARDED,
                    )
                ),
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


async def build_device_match_forecast_response(
    session: AsyncSession,
    *,
    match_uuid: UUID,
    device_uuid: UUID,
    now: datetime,
    record_missed: bool = True,
) -> MatchForecastResponse | None:
    """Return only the requested device's current schedule-revision timeline."""

    settings = get_settings()
    context = await load_play_context(
        session,
        match_uuid=match_uuid,
        device_uuid=device_uuid,
        settings=settings,
        now=now,
        record_missed=record_missed,
    )
    if context is None:
        return None
    match = context.match
    home = await session.get(Club, match.home_club_uuid)
    away = await session.get(Club, match.away_club_uuid)
    if home is None or away is None:
        return None
    revision = context.revision
    opens_at = revision.kickoff_at - timedelta(hours=24) if revision is not None else None
    closes_at = revision.kickoff_at + timedelta(minutes=45) if revision is not None else None
    seconds_until = (
        max(0, math.ceil((opens_at - now).total_seconds()))
        if opens_at is not None
        else 0
    )
    empty_presentation = PresentationResponse(
        started_at=None,
        duration_seconds=settings.simulation_presentation_seconds,
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
        "prediction_due_at": opens_at or match.prediction_due_at,
        "seconds_until_generation": seconds_until,
        "seconds_until_play": seconds_until,
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
        "schedule_revision_uuid": revision.revision_uuid if revision is not None else None,
        "schedule_revision_number": revision.revision_number if revision is not None else None,
        "window_opens_at": opens_at,
        "window_closes_at": closes_at,
        "data_current": context.data_current,
    }
    simulation = context.simulation
    if simulation is None:
        if revision is None:
            lifecycle = "unavailable"
        elif revision.canonical_status is FixtureStatus.POSTPONED:
            lifecycle = "postponed"
        elif revision.canonical_status is FixtureStatus.CANCELLED:
            lifecycle = "cancelled"
        elif opens_at is None or closes_at is None:
            lifecycle = "unavailable"
        elif now < opens_at:
            lifecycle = "locked"
        elif not context.data_current:
            lifecycle = "stale"
        elif now <= closes_at:
            lifecycle = "available"
        else:
            lifecycle = "missed"
        return MatchForecastResponse(
            **common,
            lifecycle_state=lifecycle,
            prediction=None,
            presentation=empty_presentation,
            simulation=None,
        )
    if simulation.state in ("missed", "void"):
        return MatchForecastResponse(
            **common,
            lifecycle_state=simulation.state,
            prediction=None,
            presentation=empty_presentation,
            simulation=None,
            play_classification=simulation.play_classification,
            generated_at=simulation.generated_at,
        )

    if (
        simulation.generated_at is None
        or simulation.feature_cutoff_at is None
        or simulation.feature_snapshot_checksum is None
        or simulation.model_version is None
        or simulation.expected_home_goals is None
        or simulation.expected_away_goals is None
        or simulation.home_win_probability is None
        or simulation.draw_probability is None
        or simulation.away_win_probability is None
        or simulation.statistics_distribution is None
        or simulation.expected_lineups is None
        or simulation.home_goals is None
        or simulation.away_goals is None
        or simulation.statistics is None
        or simulation.events is None
        or simulation.simulation_checksum is None
        or simulation.presentation_started_at is None
    ):
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
    return MatchForecastResponse(
        **common,
        lifecycle_state="complete" if clock.complete else "live",
        play_classification=simulation.play_classification,
        generated_at=simulation.generated_at,
        prediction=PredictionResponse(
            prediction_version_uuid=None,
            version_number=None,
            locked_at=simulation.generated_at,
            feature_cutoff_at=simulation.feature_cutoff_at,
            feature_snapshot_checksum=simulation.feature_snapshot_checksum,
            model_version=simulation.model_version,
            expected_home_goals=simulation.expected_home_goals,
            expected_away_goals=simulation.expected_away_goals,
            home_win_probability=simulation.home_win_probability,
            draw_probability=simulation.draw_probability,
            away_win_probability=simulation.away_win_probability,
            statistics_distribution=simulation.statistics_distribution,
            expected_lineups=simulation.expected_lineups,
        ),
        presentation=PresentationResponse(
            started_at=simulation.presentation_started_at,
            duration_seconds=simulation.presentation_duration_seconds,
            phase=clock.phase,
            elapsed_seconds=clock.elapsed_seconds,
            remaining_seconds=clock.remaining_seconds,
            football_second=clock.football_second,
            complete=clock.complete,
        ),
        simulation=SimulationResponse(
            simulation_uuid=simulation.device_simulation_uuid,
            checksum=simulation.simulation_checksum,
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
    device_uuid: Annotated[UUID, Query()],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MatchForecastResponse:
    response = await build_device_match_forecast_response(
        session,
        match_uuid=match_uuid,
        device_uuid=device_uuid,
        now=datetime.now(UTC),
    )
    if response is None:
        raise HTTPException(status_code=404, detail="match not found")
    await session.commit()
    return response


async def build_match_forecast_response(
    session: AsyncSession, *, match_uuid: UUID, now: datetime
) -> MatchForecastResponse | None:
    """Read-only presentation of retained legacy shared simulations."""

    home_club = aliased(Club)
    away_club = aliased(Club)
    row = (
        await session.execute(
            select(Match, home_club, away_club)
            .join(home_club, home_club.club_uuid == Match.home_club_uuid)
            .join(away_club, away_club.club_uuid == Match.away_club_uuid)
            .where(Match.match_uuid == match_uuid)
        )
    ).one_or_none()
    if row is None:
        return None
    match, home, away = row
    prediction = await session.scalar(
        select(PredictionVersion).where(
            PredictionVersion.match_uuid == match_uuid,
            PredictionVersion.state.in_(
                (PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)
            ),
        )
    )
    seconds_until = max(0, math.ceil((match.prediction_due_at - now).total_seconds()))
    empty = PresentationResponse(
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
            lifecycle = (
                "unavailable"
                if latest_job is not None and latest_job.status is JobStatus.FAILED
                else "generating" if now >= match.prediction_due_at else "countdown"
            )
        return MatchForecastResponse(
            **common,
            lifecycle_state=lifecycle,
            prediction=None,
            presentation=empty,
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
            presentation=empty,
            simulation=None,
        )
    clock = presentation_clock(
        started_at=simulation.presentation_started_at,
        duration_seconds=simulation.presentation_duration_seconds,
        now=now,
    )
    events = [event for event in simulation.events if event_is_visible(event, clock)]
    score_home = int(events[-1].get("home_score", 0)) if events else 0
    score_away = int(events[-1].get("away_score", 0)) if events else 0
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
        presentation=PresentationResponse(
            started_at=simulation.presentation_started_at,
            duration_seconds=simulation.presentation_duration_seconds,
            phase=clock.phase,
            elapsed_seconds=clock.elapsed_seconds,
            remaining_seconds=clock.remaining_seconds,
            football_second=clock.football_second,
            complete=clock.complete,
        ),
        simulation=SimulationResponse(
            simulation_uuid=simulation.simulation_uuid,
            checksum=simulation.checksum,
            scoreboard_home=score_home,
            scoreboard_away=score_away,
            events=events,
            visible_statistics=_visible_statistics(events),
            final_score=(
                {"home": simulation.home_goals, "away": simulation.away_goals}
                if clock.complete
                else None
            ),
            final_statistics=simulation.statistics if clock.complete else None,
        ),
    )


@router.post("/{match_uuid}/play", response_model=MatchForecastResponse)
async def play_match(
    match_uuid: UUID,
    request: PlayRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MatchForecastResponse:
    now = datetime.now(UTC)
    try:
        await play_device_simulation(
            session,
            match_uuid=match_uuid,
            device_uuid=request.device_uuid,
            settings=get_settings(),
            now=now,
        )
    except UserPlayError as error:
        if error.code == "play_window_missed":
            await session.commit()
        else:
            await session.rollback()
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": str(error)},
        ) from error
    except LineupCoverageError as error:
        await session.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "lineup_coverage_unavailable",
                "message": (
                    "Player data is still synchronizing for this fixture. "
                    "Try Play again after local synchronization completes."
                ),
            },
            headers={"Retry-After": "300"},
        ) from error
    response = await build_device_match_forecast_response(
        session,
        match_uuid=match_uuid,
        device_uuid=request.device_uuid,
        now=now,
        record_missed=False,
    )
    if response is None:  # pragma: no cover - protected by the locked Play transaction
        await session.rollback()
        raise HTTPException(status_code=404, detail="match not found")
    await session.commit()
    return response
