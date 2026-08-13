"""Transactional execution of one revision-scoped forecast task delivery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import (
    FixtureStatus,
    ForecastTaskState,
    IdentityReviewState,
    JobStatus,
    KickoffPrecision,
    PredictionState,
)
from prem_engine_api.domain.models import (
    FixtureScheduleRevision,
    ForecastTaskSchedule,
    JobRun,
    Match,
    PredictionVersion,
)
from prem_engine_api.forecasting.generation import ForecastGenerationError, lock_forecast
from prem_engine_api.forecasting.inference import (
    ArtifactConfigurationError,
    ForecastInputUnavailableError,
    OfficialArtifactForecastFactory,
)
from prem_engine_api.forecasting.lineups import LineupCoverageError
from prem_engine_api.jobs.leases import GENERATE_PREDICTION_JOB, JobLeaseError, fail_job
from prem_engine_api.scheduling.forecast_tasks import (
    ForecastMonitoringPayload,
    ForecastTaskPayload,
    SnapshotFinalizationPayload,
    forecast_task_id,
    monitor_task_id,
    snapshot_task_id,
)
from prem_engine_api.snapshots.publisher import PublicSnapshotPublisher

logger = structlog.get_logger()


class ForecastTaskRejected(RuntimeError):
    """Raised when a delivery does not match the persisted task identity."""


@dataclass(frozen=True)
class ForecastDeliveryResult:
    outcome: Literal["created", "reused", "stale", "duplicate", "early", "busy"]
    status_code: int


@dataclass(frozen=True)
class PreparedDelivery:
    job_uuid: UUID
    worker_id: str
    cutoff: datetime


@dataclass(frozen=True)
class PreparedExisting:
    prediction_version_uuid: UUID


@dataclass(frozen=True)
class SnapshotFinalizationResult:
    outcome: Literal["published", "stale", "early", "disabled", "busy"]
    status_code: int


@dataclass(frozen=True)
class ForecastMonitoringResult:
    outcome: Literal["healthy", "missing", "stale", "early"]
    status_code: int


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


class ForecastTaskService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        settings: Settings,
        forecast_factory: OfficialArtifactForecastFactory | None = None,
        snapshot_publisher: PublicSnapshotPublisher | None = None,
    ) -> None:
        self._sessions = session_factory
        self._settings = settings
        self._factory = forecast_factory or OfficialArtifactForecastFactory(settings)
        self._publisher = snapshot_publisher or PublicSnapshotPublisher(
            session_factory,
            settings=settings,
        )

    async def close(self) -> None:
        await self._publisher.close()

    async def ready(self) -> None:
        """Verify the database boundary used by Cloud Run startup checks."""

        async with self._sessions() as session:
            await session.execute(text("SELECT 1"))

    async def deliver(
        self,
        payload: ForecastTaskPayload,
        *,
        task_name: str,
        retry_count: int,
        now: datetime | None = None,
    ) -> ForecastDeliveryResult:
        delivery_time = now or datetime.now(UTC)
        prepared_or_result = await self._prepare(
            payload,
            task_name=task_name,
            retry_count=retry_count,
            now=delivery_time,
        )
        if isinstance(prepared_or_result, ForecastDeliveryResult):
            return prepared_or_result
        created = False
        if isinstance(prepared_or_result, PreparedDelivery):
            prepared = prepared_or_result
            try:
                async with self._sessions() as session:
                    package = await self._factory.build(
                        session,
                        match_uuid=payload.match_uuid,
                        cutoff=prepared.cutoff,
                    )
                    outcome = await lock_forecast(
                        session,
                        job_uuid=prepared.job_uuid,
                        worker_id=prepared.worker_id,
                        package=package,
                        locked_at=datetime.now(UTC),
                        presentation_duration_seconds=(
                            self._settings.simulation_presentation_seconds
                        ),
                        actor="cloud-tasks-forecast",
                        enqueue_standings_job=False,
                    )
                    await session.commit()
                created = outcome.created
            except Exception as error:
                code = _error_code(error)
                logger.exception(
                    "forecast_task_delivery_failed",
                    task_id=task_name,
                    error_code=code,
                    retry_count=retry_count,
                )
                await self._record_failure(
                    payload,
                    prepared=prepared,
                    now=datetime.now(UTC),
                    error_code=code,
                )
                return ForecastDeliveryResult("busy", 500)
        try:
            await self._publish_forecast(
                payload,
                now=datetime.now(UTC),
            )
            await self._mark_succeeded(payload, now=datetime.now(UTC))
        except Exception:
            logger.exception(
                "snapshot_publication_failed",
                task_id=task_name,
                error_code="snapshot_publication_failed",
                retry_count=retry_count,
            )
            await self._record_publication_failure(payload, now=datetime.now(UTC))
            return ForecastDeliveryResult("busy", 500)
        return ForecastDeliveryResult("created" if created else "reused", 200)

    async def finalize_snapshot(
        self,
        payload: SnapshotFinalizationPayload,
        *,
        task_name: str,
        now: datetime | None = None,
    ) -> SnapshotFinalizationResult:
        finalization_time = now or datetime.now(UTC)
        if finalization_time.tzinfo is None or finalization_time.utcoffset() is None:
            raise ValueError("snapshot finalization time must include a timezone")
        if task_name != snapshot_task_id(payload.schedule_revision_uuid):
            raise ForecastTaskRejected("snapshot task header does not match the revision")
        if not self._publisher.enabled:
            return SnapshotFinalizationResult("disabled", 200)
        async with self._sessions() as session:
            revision = await session.get(
                FixtureScheduleRevision,
                payload.schedule_revision_uuid,
            )
            match = await session.get(Match, payload.match_uuid)
            prediction_version_uuid = await session.scalar(
                select(PredictionVersion.prediction_version_uuid).where(
                    PredictionVersion.match_uuid == payload.match_uuid,
                    PredictionVersion.state.in_(
                        (PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)
                    ),
                )
            )
        if (
            revision is None
            or match is None
            or revision.match_uuid != payload.match_uuid
            or revision.superseded_at is not None
            or revision.canonical_status != FixtureStatus.SCHEDULED
            or match.status != FixtureStatus.SCHEDULED
            or match.current_kickoff_at != revision.kickoff_at
        ):
            return SnapshotFinalizationResult("stale", 200)
        if prediction_version_uuid is None:
            return SnapshotFinalizationResult("busy", 503)
        metadata = await self._publisher.forecast_metadata(
            match_uuid=payload.match_uuid,
            prediction_version_uuid=prediction_version_uuid,
        )
        if metadata is None:
            return SnapshotFinalizationResult("stale", 200)
        if finalization_time < metadata.reveal_at:
            wait_seconds = (metadata.reveal_at - finalization_time).total_seconds()
            if wait_seconds > self._settings.simulation_presentation_seconds:
                return SnapshotFinalizationResult("early", 425)
            await asyncio.sleep(wait_seconds)
            finalization_time = metadata.reveal_at if now is not None else datetime.now(UTC)
        try:
            await self._publisher.publish_forecast(
                match_uuid=payload.match_uuid,
                now=finalization_time,
            )
            await self._publisher.publish_standings(now=finalization_time)
        except Exception:
            logger.exception(
                "snapshot_publication_failed",
                task_id=task_name,
                error_code="snapshot_finalization_failed",
            )
            return SnapshotFinalizationResult("busy", 500)
        return SnapshotFinalizationResult("published", 200)

    async def monitor(
        self,
        payload: ForecastMonitoringPayload,
        *,
        task_name: str,
        now: datetime | None = None,
    ) -> ForecastMonitoringResult:
        monitoring_time = now or datetime.now(UTC)
        if monitoring_time.tzinfo is None or monitoring_time.utcoffset() is None:
            raise ValueError("forecast monitoring time must include a timezone")
        if task_name != monitor_task_id(payload.schedule_revision_uuid):
            raise ForecastTaskRejected("monitor task header does not match the revision")
        async with self._sessions() as session:
            ledger = await session.scalar(
                select(ForecastTaskSchedule).where(
                    ForecastTaskSchedule.schedule_revision_uuid == payload.schedule_revision_uuid
                )
            )
            if ledger is None or ledger.match_uuid != payload.match_uuid:
                raise ForecastTaskRejected("monitor task does not match the scheduling ledger")
            revision = await session.get(
                FixtureScheduleRevision,
                payload.schedule_revision_uuid,
            )
            match = await session.get(Match, payload.match_uuid)
            prediction_version_uuid = await session.scalar(
                select(PredictionVersion.prediction_version_uuid).where(
                    PredictionVersion.match_uuid == payload.match_uuid,
                    PredictionVersion.state.in_(
                        (PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)
                    ),
                )
            )
        current = (
            revision is not None
            and match is not None
            and revision.match_uuid == payload.match_uuid
            and revision.superseded_at is None
            and revision.canonical_status == FixtureStatus.SCHEDULED
            and match.status == FixtureStatus.SCHEDULED
            and match.identity_review_state == IdentityReviewState.RESOLVED
            and match.kickoff_precision == KickoffPrecision.EXACT
            and match.current_kickoff_at == revision.kickoff_at
            and match.prediction_due_at == ledger.schedule_time
        )
        if not current:
            return ForecastMonitoringResult("stale", 200)
        monitor_after = ledger.schedule_time + timedelta(
            seconds=self._settings.forecast_monitoring_grace_seconds
        )
        if monitoring_time < monitor_after:
            return ForecastMonitoringResult("early", 425)
        if prediction_version_uuid is not None:
            return ForecastMonitoringResult("healthy", 200)
        logger.error(
            "t24_forecast_missing",
            task_id=task_name,
            match_uuid=str(payload.match_uuid),
        )
        return ForecastMonitoringResult("missing", 200)

    async def _prepare(
        self,
        payload: ForecastTaskPayload,
        *,
        task_name: str,
        retry_count: int,
        now: datetime,
    ) -> PreparedDelivery | PreparedExisting | ForecastDeliveryResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("delivery time must include a timezone")
        expected_task_id = forecast_task_id(payload.match_uuid, payload.revision_number)
        if task_name != expected_task_id:
            raise ForecastTaskRejected("task header does not match the request revision")
        async with self._sessions() as session:
            ledger_preview = await session.scalar(
                select(ForecastTaskSchedule).where(
                    ForecastTaskSchedule.schedule_revision_uuid == payload.schedule_revision_uuid
                )
            )
            if (
                ledger_preview is None
                or ledger_preview.match_uuid != payload.match_uuid
                or ledger_preview.task_id != task_name
            ):
                raise ForecastTaskRejected("task does not match the scheduling ledger")
            match = await session.scalar(
                select(Match).where(Match.match_uuid == payload.match_uuid).with_for_update()
            )
            revision = await session.scalar(
                select(FixtureScheduleRevision)
                .where(FixtureScheduleRevision.revision_uuid == payload.schedule_revision_uuid)
                .with_for_update()
            )
            job = await session.scalar(
                select(JobRun)
                .where(
                    JobRun.idempotency_key
                    == (f"{GENERATE_PREDICTION_JOB}:{payload.match_uuid}:{payload.revision_number}")
                )
                .with_for_update()
            )
            ledger = await session.scalar(
                select(ForecastTaskSchedule)
                .where(
                    ForecastTaskSchedule.schedule_revision_uuid == payload.schedule_revision_uuid
                )
                .with_for_update()
            )
            if (
                ledger is None
                or ledger.match_uuid != payload.match_uuid
                or ledger.task_id != task_name
            ):
                raise ForecastTaskRejected("task does not match the scheduling ledger")
            ledger.delivery_count += 1
            ledger.first_delivery_at = ledger.first_delivery_at or now
            if ledger.state in (ForecastTaskState.SUCCEEDED, ForecastTaskState.STALE):
                await session.commit()
                return ForecastDeliveryResult("duplicate", 200)
            stale = (
                revision is None
                or match is None
                or revision.match_uuid != payload.match_uuid
                or revision.revision_number != payload.revision_number
                or revision.superseded_at is not None
                or revision.canonical_status != FixtureStatus.SCHEDULED
                or match.status != FixtureStatus.SCHEDULED
                or match.identity_review_state != IdentityReviewState.RESOLVED
                or match.kickoff_precision != KickoffPrecision.EXACT
                or match.current_kickoff_at != revision.kickoff_at
                or match.prediction_due_at != ledger.schedule_time
            )
            if stale:
                ledger.state = ForecastTaskState.STALE
                ledger.completed_at = now
                ledger.last_error_code = "schedule_revision_stale"
                if job is not None and job.status in (
                    JobStatus.PENDING,
                    JobStatus.LEASED,
                    JobStatus.RUNNING,
                ):
                    job.status = JobStatus.CANCELLED
                    job.finished_at = now
                    job.lease_owner = None
                    job.lease_expires_at = None
                await session.commit()
                logger.info(
                    "forecast_task_stale",
                    task_id=task_name,
                    match_uuid=str(payload.match_uuid),
                )
                return ForecastDeliveryResult("stale", 200)

            existing = await session.scalar(
                select(PredictionVersion.prediction_version_uuid).where(
                    PredictionVersion.match_uuid == payload.match_uuid,
                    PredictionVersion.state.in_(
                        (PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)
                    ),
                )
            )
            if existing is not None:
                ledger.state = ForecastTaskState.PROCESSING
                ledger.completed_at = None
                ledger.last_error_code = None
                if job is not None and job.status != JobStatus.SUCCEEDED:
                    job.status = JobStatus.SUCCEEDED
                    job.finished_at = now
                    job.lease_owner = None
                    job.lease_expires_at = None
                await session.commit()
                return PreparedExisting(existing)
            if match is not None and now < match.prediction_due_at:
                ledger.state = ForecastTaskState.ENQUEUED
                ledger.last_error_code = "delivery_before_t24"
                await session.commit()
                return ForecastDeliveryResult("early", 425)
            if job is None:
                raise ForecastTaskRejected("forecast generation job is missing")
            if match is None:  # pragma: no cover - included in the stale branch above
                raise ForecastTaskRejected("forecast match is missing")
            if (
                job.status in (JobStatus.LEASED, JobStatus.RUNNING)
                and job.lease_expires_at is not None
                and job.lease_expires_at > now
            ):
                ledger.state = ForecastTaskState.ENQUEUED
                ledger.last_error_code = "generation_already_running"
                await session.commit()
                return ForecastDeliveryResult("busy", 503)
            if job.attempt_count >= self._settings.forecast_job_max_attempts:
                ledger.state = ForecastTaskState.FAILED
                ledger.completed_at = now
                ledger.last_error_code = "forecast_attempts_exhausted"
                job.status = JobStatus.FAILED
                job.finished_at = now
                job.lease_owner = None
                job.lease_expires_at = None
                await session.commit()
                logger.error("forecast_task_terminal_failure", task_id=task_name)
                return ForecastDeliveryResult("busy", 500)
            worker_id = f"cloud-task:{task_name}:{retry_count}"
            job.status = JobStatus.RUNNING
            job.lease_owner = worker_id
            job.lease_expires_at = now + timedelta(
                seconds=self._settings.forecast_job_lease_seconds
            )
            job.attempt_count += 1
            job.last_error_code = None
            job.started_at = now
            job.finished_at = None
            ledger.state = ForecastTaskState.PROCESSING
            ledger.last_error_code = None
            cutoff = match.prediction_due_at
            await session.commit()
            return PreparedDelivery(job.job_uuid, worker_id, cutoff)

    async def _publish_forecast(
        self,
        payload: ForecastTaskPayload,
        *,
        now: datetime,
    ) -> None:
        if not self._publisher.enabled:
            return
        await self._publisher.publish_forecast(match_uuid=payload.match_uuid, now=now)

    async def _mark_succeeded(
        self,
        payload: ForecastTaskPayload,
        *,
        now: datetime,
    ) -> None:
        async with self._sessions() as session:
            ledger = await session.scalar(
                select(ForecastTaskSchedule)
                .where(
                    ForecastTaskSchedule.schedule_revision_uuid == payload.schedule_revision_uuid
                )
                .with_for_update()
            )
            if ledger is None:
                raise ForecastTaskRejected("forecast task ledger disappeared")
            ledger.state = ForecastTaskState.SUCCEEDED
            ledger.completed_at = now
            ledger.last_error_code = None
            await session.commit()

    async def _record_publication_failure(
        self,
        payload: ForecastTaskPayload,
        *,
        now: datetime,
    ) -> None:
        async with self._sessions() as session:
            ledger = await session.scalar(
                select(ForecastTaskSchedule)
                .where(
                    ForecastTaskSchedule.schedule_revision_uuid == payload.schedule_revision_uuid
                )
                .with_for_update()
            )
            if ledger is not None:
                ledger.state = ForecastTaskState.ENQUEUED
                ledger.completed_at = None
                ledger.last_error_code = "snapshot_publication_failed"
            await session.commit()

    async def _record_failure(
        self,
        payload: ForecastTaskPayload,
        *,
        prepared: PreparedDelivery,
        now: datetime,
        error_code: str,
    ) -> None:
        try:
            async with self._sessions() as session:
                status = await fail_job(
                    session,
                    job_uuid=prepared.job_uuid,
                    worker_id=prepared.worker_id,
                    now=now,
                    error_code=error_code,
                    max_attempts=self._settings.forecast_job_max_attempts,
                    retry_delay=timedelta(0),
                )
                ledger = await session.scalar(
                    select(ForecastTaskSchedule)
                    .where(
                        ForecastTaskSchedule.schedule_revision_uuid
                        == payload.schedule_revision_uuid
                    )
                    .with_for_update()
                )
                if ledger is not None:
                    ledger.state = (
                        ForecastTaskState.FAILED
                        if status == JobStatus.FAILED
                        else ForecastTaskState.ENQUEUED
                    )
                    ledger.completed_at = now if status == JobStatus.FAILED else None
                    ledger.last_error_code = error_code
                await session.commit()
                if status == JobStatus.FAILED:
                    logger.error(
                        "forecast_task_terminal_failure",
                        task_id=ledger.task_id if ledger is not None else "unknown",
                        error_code=error_code,
                    )
        except JobLeaseError:
            logger.warning(
                "forecast_task_failure_not_recorded",
                task_id=prepared.worker_id,
                error_code="lease_owner_changed",
            )
