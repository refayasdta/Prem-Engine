"""One-shot dispatcher for automatic T-24 forecast generation."""

from __future__ import annotations

import asyncio
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prem_engine_api.config import Settings, get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.forecasting.generation import ForecastGenerationError, lock_forecast
from prem_engine_api.forecasting.inference import (
    ArtifactConfigurationError,
    ForecastInputUnavailableError,
    OfficialArtifactForecastFactory,
)
from prem_engine_api.forecasting.lineups import LineupCoverageError
from prem_engine_api.jobs.leases import (
    GENERATE_PREDICTION_JOB,
    RECALCULATE_SIMULATED_STANDINGS_JOB,
    JobLeaseError,
    claim_due_jobs,
    complete_job,
    enqueue_prediction_jobs,
    fail_job,
    start_job,
)
from prem_engine_api.jobs.standings import recalculate_simulated_standings

logger = structlog.get_logger()


@dataclass(frozen=True)
class DispatchSummary:
    jobs_enqueued: int
    jobs_claimed: int
    forecasts_created: int
    forecasts_reused: int
    standings_recalculated: int
    jobs_retried: int
    jobs_failed: int


def _error_code(error: Exception) -> str:
    if isinstance(error, LineupCoverageError):
        return "insufficient_lineup_coverage"
    if isinstance(error, ArtifactConfigurationError):
        return "invalid_model_artifact"
    if isinstance(error, ForecastInputUnavailableError):
        return "forecast_input_unavailable"
    if isinstance(error, ForecastGenerationError):
        return "forecast_generation_rejected"
    if isinstance(error, JobLeaseError):
        return "job_lease_invalid"
    return "unhandled_generation_error"


async def dispatch_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    worker_id: str,
    now: datetime | None = None,
    forecast_factory: OfficialArtifactForecastFactory | None = None,
) -> DispatchSummary:
    """Enqueue, lease, and execute one bounded batch; safe for minute cron calls."""

    dispatch_time = now or datetime.now(UTC)
    factory = forecast_factory or OfficialArtifactForecastFactory(settings)
    async with session_factory() as session:
        enqueued = await enqueue_prediction_jobs(session, now=dispatch_time)
        claimed = await claim_due_jobs(
            session,
            worker_id=worker_id,
            now=dispatch_time,
            lease_duration=timedelta(seconds=settings.forecast_job_lease_seconds),
            limit=settings.forecast_dispatch_batch_size,
            max_attempts=settings.forecast_job_max_attempts,
            job_types=(GENERATE_PREDICTION_JOB, RECALCULATE_SIMULATED_STANDINGS_JOB),
        )
        await session.commit()

    created = 0
    reused = 0
    standings_recalculated = 0
    retried = 0
    failed = 0
    for claimed_job in claimed:
        if claimed_job.match_uuid is None:
            continue
        try:
            async with session_factory() as session:
                started_at = datetime.now(UTC)
                await start_job(
                    session,
                    job_uuid=claimed_job.job_uuid,
                    worker_id=worker_id,
                    now=started_at,
                )
                await session.commit()
            async with session_factory() as session:
                completed_at = datetime.now(UTC)
                if claimed_job.job_type == GENERATE_PREDICTION_JOB:
                    package = await factory.build(
                        session,
                        match_uuid=claimed_job.match_uuid,
                        cutoff=(await _job_cutoff(session, claimed_job.match_uuid)),
                    )
                    outcome = await lock_forecast(
                        session,
                        job_uuid=claimed_job.job_uuid,
                        worker_id=worker_id,
                        package=package,
                        locked_at=completed_at,
                        presentation_duration_seconds=settings.simulation_presentation_seconds,
                    )
                    created += int(outcome.created)
                    reused += int(not outcome.created)
                elif claimed_job.job_type == RECALCULATE_SIMULATED_STANDINGS_JOB:
                    await recalculate_simulated_standings(
                        session,
                        match_uuid=claimed_job.match_uuid,
                        as_of=completed_at,
                    )
                    await complete_job(
                        session,
                        job_uuid=claimed_job.job_uuid,
                        worker_id=worker_id,
                        now=completed_at,
                    )
                    standings_recalculated += 1
                else:  # pragma: no cover - protected by the lease filter
                    raise RuntimeError("dispatcher claimed an unsupported job type")
                await session.commit()
        except Exception as error:
            code = _error_code(error)
            logger.exception(
                "forecast_job_failed",
                job_uuid=str(claimed_job.job_uuid),
                error_code=code,
            )
            try:
                async with session_factory() as session:
                    status = await fail_job(
                        session,
                        job_uuid=claimed_job.job_uuid,
                        worker_id=worker_id,
                        now=datetime.now(UTC),
                        error_code=code,
                        max_attempts=settings.forecast_job_max_attempts,
                        retry_delay=timedelta(seconds=settings.forecast_retry_delay_seconds),
                    )
                    await session.commit()
                if status.value == "failed":
                    failed += 1
                else:
                    retried += 1
            except JobLeaseError:
                logger.warning(
                    "forecast_job_failure_not_recorded",
                    job_uuid=str(claimed_job.job_uuid),
                    error_code="lease_owner_changed",
                )
                failed += 1
    return DispatchSummary(
        jobs_enqueued=enqueued,
        jobs_claimed=len(claimed),
        forecasts_created=created,
        forecasts_reused=reused,
        standings_recalculated=standings_recalculated,
        jobs_retried=retried,
        jobs_failed=failed,
    )


async def _job_cutoff(session: AsyncSession, match_uuid: object) -> datetime:
    from sqlalchemy import select

    from prem_engine_api.domain.models import Match

    cutoff = await session.scalar(
        select(Match.prediction_due_at).where(Match.match_uuid == match_uuid)
    )
    if cutoff is None:
        raise ForecastInputUnavailableError("forecast match disappeared")
    return cutoff


async def _run() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    try:
        summary = await dispatch_once(
            create_session_factory(engine),
            settings=settings,
            worker_id=worker_id,
        )
        logger.info("forecast_dispatch_complete", **summary.__dict__)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
