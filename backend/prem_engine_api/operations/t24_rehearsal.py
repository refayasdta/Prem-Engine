"""Transactional rehearsal of the artifact-backed T-24 forecast path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.api.forecasts import build_match_forecast_response
from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import JobStatus, PredictionState
from prem_engine_api.domain.models import JobRun, Match, PredictionVersion, StoredSimulation
from prem_engine_api.forecasting.generation import lock_forecast
from prem_engine_api.forecasting.inference import OfficialArtifactForecastFactory
from prem_engine_api.jobs.leases import GENERATE_PREDICTION_JOB


class T24RehearsalError(RuntimeError):
    """Raised when a match cannot complete the isolated rehearsal."""


@dataclass(frozen=True, slots=True)
class T24RehearsalReport:
    """Evidence produced by one rollback-only rehearsal."""

    match_uuid: UUID
    home_starters: int
    away_starters: int
    home_substitutes: int
    away_substitutes: int
    outcome_model_version: str
    statistics_model_version: str
    prediction_version_uuid: UUID
    simulation_uuid: UUID
    simulation_event_count: int
    live_state: str
    complete_state: str
    final_score_withheld_while_live: bool
    final_score_revealed_when_complete: bool


async def rehearse_t24_forecast(
    session: AsyncSession,
    *,
    settings: Settings,
    match_uuid: UUID,
) -> T24RehearsalReport:
    """Exercise real artifacts, persistence, and API reads inside a caller-owned transaction."""

    if settings.app_env.casefold() == "production":
        raise T24RehearsalError("the rollback rehearsal is disabled in production")

    match = await session.get(Match, match_uuid)
    if match is None:
        raise T24RehearsalError("the rehearsal match does not exist")

    active_prediction = await session.scalar(
        select(PredictionVersion).where(
            PredictionVersion.match_uuid == match_uuid,
            PredictionVersion.state.in_((PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)),
        )
    )
    if active_prediction is not None:
        raise T24RehearsalError("the rehearsal requires a match without an active prediction")

    package = await OfficialArtifactForecastFactory(settings).build(
        session,
        match_uuid=match_uuid,
        cutoff=match.prediction_due_at,
    )
    locked_at = match.prediction_due_at + timedelta(seconds=2)
    worker_id = f"t24-rehearsal-{uuid4()}"
    job = JobRun(
        idempotency_key=f"t24-rehearsal:{match_uuid}:{uuid4()}",
        job_type=GENERATE_PREDICTION_JOB,
        status=JobStatus.RUNNING,
        match_uuid=match_uuid,
        due_at=match.prediction_due_at,
        lease_owner=worker_id,
        lease_expires_at=locked_at + timedelta(minutes=5),
        attempt_count=1,
        started_at=locked_at - timedelta(seconds=1),
    )
    session.add(job)
    await session.flush()

    outcome = await lock_forecast(
        session,
        job_uuid=job.job_uuid,
        worker_id=worker_id,
        package=package,
        locked_at=locked_at,
        presentation_duration_seconds=settings.simulation_presentation_seconds,
        actor="t24-rehearsal",
    )
    if not outcome.created:
        raise T24RehearsalError("the rehearsal unexpectedly reused an existing prediction")

    live = await build_match_forecast_response(
        session,
        match_uuid=match_uuid,
        now=locked_at + timedelta(seconds=10),
    )
    complete = await build_match_forecast_response(
        session,
        match_uuid=match_uuid,
        now=locked_at + timedelta(seconds=61),
    )
    if live is None or complete is None or live.simulation is None or complete.simulation is None:
        raise T24RehearsalError("the public forecast response is incomplete")
    if live.lifecycle_state != "live" or complete.lifecycle_state != "complete":
        raise T24RehearsalError("the public forecast did not traverse live and complete states")
    if live.simulation.final_score is not None or complete.simulation.final_score is None:
        raise T24RehearsalError("the public forecast revealed its final score at the wrong time")

    simulation = await session.scalar(
        select(StoredSimulation).where(
            StoredSimulation.prediction_version_uuid == outcome.prediction_version_uuid
        )
    )
    if simulation is None:
        raise T24RehearsalError("the rehearsal did not persist a simulation")

    return T24RehearsalReport(
        match_uuid=match_uuid,
        home_starters=len(package.home_lineup.starters),
        away_starters=len(package.away_lineup.starters),
        home_substitutes=len(package.home_lineup.substitutes),
        away_substitutes=len(package.away_lineup.substitutes),
        outcome_model_version=package.forecast.outcome_model_version,
        statistics_model_version=package.forecast.statistics_model_version,
        prediction_version_uuid=outcome.prediction_version_uuid,
        simulation_uuid=outcome.simulation_uuid,
        simulation_event_count=len(simulation.events),
        live_state=live.lifecycle_state,
        complete_state=complete.lifecycle_state,
        final_score_withheld_while_live=live.simulation.final_score is None,
        final_score_revealed_when_complete=complete.simulation.final_score is not None,
    )
