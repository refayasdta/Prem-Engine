"""Durable, idempotent creation of exact T-24 Cloud Tasks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

import structlog
from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2
from google.protobuf import duration_pb2, timestamp_pb2  # type: ignore[import-untyped]
from sqlalchemy import and_, exists, select
from sqlalchemy.dialects.postgresql import insert
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
from prem_engine_api.jobs.leases import GENERATE_PREDICTION_JOB

logger = structlog.get_logger()


@dataclass(frozen=True)
class ForecastTaskPayload:
    match_uuid: UUID
    schedule_revision_uuid: UUID
    revision_number: int

    def json_bytes(self) -> bytes:
        return json.dumps(
            {
                "match_uuid": str(self.match_uuid),
                "schedule_revision_uuid": str(self.schedule_revision_uuid),
                "revision_number": self.revision_number,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()


@dataclass(frozen=True)
class PendingForecastTask:
    schedule_uuid: UUID
    task_id: str
    schedule_time: datetime
    payload: ForecastTaskPayload


@dataclass(frozen=True)
class SnapshotFinalizationPayload:
    match_uuid: UUID
    schedule_revision_uuid: UUID

    def json_bytes(self) -> bytes:
        return json.dumps(
            {
                "match_uuid": str(self.match_uuid),
                "schedule_revision_uuid": str(self.schedule_revision_uuid),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()


@dataclass(frozen=True)
class PendingSnapshotTask:
    task_id: str
    schedule_time: datetime
    payload: SnapshotFinalizationPayload


@dataclass(frozen=True)
class ForecastMonitoringPayload:
    match_uuid: UUID
    schedule_revision_uuid: UUID

    def json_bytes(self) -> bytes:
        return json.dumps(
            {
                "match_uuid": str(self.match_uuid),
                "schedule_revision_uuid": str(self.schedule_revision_uuid),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()


@dataclass(frozen=True)
class PendingMonitorTask:
    task_id: str
    schedule_time: datetime
    payload: ForecastMonitoringPayload


@dataclass(frozen=True)
class ForecastTaskSyncSummary:
    reserved: int
    enqueued: int
    already_existed: int
    failed: int
    disabled: bool = False


class ForecastTaskGateway(Protocol):
    async def create(self, task: PendingForecastTask) -> tuple[str, bool]: ...


class SnapshotTaskGateway(Protocol):
    async def create_snapshot(self, task: PendingSnapshotTask) -> tuple[str, bool]: ...


class MonitorTaskGateway(Protocol):
    async def create_monitor(self, task: PendingMonitorTask) -> tuple[str, bool]: ...


def forecast_task_id(match_uuid: UUID, revision_number: int) -> str:
    if revision_number <= 0:
        raise ValueError("schedule revision number must be positive")
    return f"forecast-{match_uuid.hex}-{revision_number}"


def snapshot_task_id(schedule_revision_uuid: UUID) -> str:
    return f"snapshot-{schedule_revision_uuid.hex}"


def monitor_task_id(schedule_revision_uuid: UUID) -> str:
    return f"monitor-{schedule_revision_uuid.hex}"


class GoogleForecastTaskGateway:
    """Create authenticated HTTP tasks with deterministic names."""

    def __init__(self, settings: Settings) -> None:
        required = (
            settings.cloud_tasks_project_id,
            settings.cloud_tasks_location,
            settings.forecast_task_queue_id,
            settings.forecast_task_target_url,
            settings.forecast_task_invoker_service_account,
        )
        if any(value is None for value in required):
            raise ValueError("Cloud Tasks configuration is incomplete")
        self._project = str(settings.cloud_tasks_project_id)
        self._location = str(settings.cloud_tasks_location)
        self._queue = str(settings.forecast_task_queue_id)
        self._url = str(settings.forecast_task_target_url)
        from urllib.parse import urlsplit, urlunsplit

        target = urlsplit(self._url)
        self._audience = f"{target.scheme}://{target.netloc}"
        self._snapshot_url = urlunsplit((target.scheme, target.netloc, "/tasks/snapshot", "", ""))
        self._monitor_url = urlunsplit((target.scheme, target.netloc, "/tasks/monitor", "", ""))
        self._service_account = str(settings.forecast_task_invoker_service_account)
        self._deadline = settings.forecast_task_dispatch_deadline_seconds
        self._client = tasks_v2.CloudTasksAsyncClient()

    async def create(self, task: PendingForecastTask) -> tuple[str, bool]:
        return await self._create(
            task_id=task.task_id,
            schedule_time=task.schedule_time,
            body=task.payload.json_bytes(),
            url=self._url,
        )

    async def create_snapshot(self, task: PendingSnapshotTask) -> tuple[str, bool]:
        return await self._create(
            task_id=task.task_id,
            schedule_time=task.schedule_time,
            body=task.payload.json_bytes(),
            url=self._snapshot_url,
        )

    async def create_monitor(self, task: PendingMonitorTask) -> tuple[str, bool]:
        return await self._create(
            task_id=task.task_id,
            schedule_time=task.schedule_time,
            body=task.payload.json_bytes(),
            url=self._monitor_url,
        )

    async def _create(
        self,
        *,
        task_id: str,
        schedule_time: datetime,
        body: bytes,
        url: str,
    ) -> tuple[str, bool]:
        parent = self._client.queue_path(self._project, self._location, self._queue)
        task_name = self._client.task_path(self._project, self._location, self._queue, task_id)
        timestamp = timestamp_pb2.Timestamp()
        timestamp.FromDatetime(schedule_time)
        deadline = duration_pb2.Duration(seconds=self._deadline)
        request = tasks_v2.CreateTaskRequest(
            parent=parent,
            task=tasks_v2.Task(
                name=task_name,
                schedule_time=timestamp,
                dispatch_deadline=deadline,
                http_request=tasks_v2.HttpRequest(
                    http_method=tasks_v2.HttpMethod.POST,
                    url=url,
                    headers={"Content-Type": "application/json"},
                    body=body,
                    oidc_token=tasks_v2.OidcToken(
                        service_account_email=self._service_account,
                        audience=self._audience,
                    ),
                ),
            ),
        )
        try:
            created = await self._client.create_task(request=request)
        except AlreadyExists:
            return task_name, True
        return created.name, False


async def reserve_forecast_tasks(
    session: AsyncSession,
    *,
    now: datetime,
    horizon: timedelta,
    overdue_grace: timedelta,
) -> tuple[PendingForecastTask, ...]:
    """Persist tasks for current eligible schedule revisions before external I/O."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("scheduling time must include a timezone")
    if horizon <= timedelta(0) or overdue_grace < timedelta(0):
        raise ValueError("scheduling horizon must be positive and grace nonnegative")
    active_prediction = exists().where(
        PredictionVersion.match_uuid == Match.match_uuid,
        PredictionVersion.state.in_((PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)),
    )
    rows = (
        await session.execute(
            select(Match, FixtureScheduleRevision)
            .join(
                FixtureScheduleRevision,
                and_(
                    FixtureScheduleRevision.match_uuid == Match.match_uuid,
                    FixtureScheduleRevision.superseded_at.is_(None),
                ),
            )
            .where(
                Match.status == FixtureStatus.SCHEDULED,
                Match.identity_review_state == IdentityReviewState.RESOLVED,
                Match.kickoff_precision == KickoffPrecision.EXACT,
                Match.prediction_due_at >= now - overdue_grace,
                Match.prediction_due_at <= now + horizon,
                ~active_prediction,
            )
            .order_by(Match.prediction_due_at, Match.match_uuid)
        )
    ).all()
    for match, revision in rows:
        await session.execute(
            insert(JobRun)
            .values(
                idempotency_key=(
                    f"{GENERATE_PREDICTION_JOB}:{match.match_uuid}:{revision.revision_number}"
                ),
                job_type=GENERATE_PREDICTION_JOB,
                status=JobStatus.PENDING,
                match_uuid=match.match_uuid,
                due_at=match.prediction_due_at,
                attempt_count=0,
            )
            .on_conflict_do_nothing(index_elements=[JobRun.idempotency_key])
        )
        await session.execute(
            insert(ForecastTaskSchedule)
            .values(
                match_uuid=match.match_uuid,
                schedule_revision_uuid=revision.revision_uuid,
                task_id=forecast_task_id(match.match_uuid, revision.revision_number),
                state=ForecastTaskState.PENDING,
                schedule_time=match.prediction_due_at,
                delivery_count=0,
            )
            .on_conflict_do_nothing(index_elements=[ForecastTaskSchedule.schedule_revision_uuid])
        )
    await session.flush()
    pending_rows = (
        await session.execute(
            select(ForecastTaskSchedule, FixtureScheduleRevision, Match)
            .join(
                FixtureScheduleRevision,
                FixtureScheduleRevision.revision_uuid
                == ForecastTaskSchedule.schedule_revision_uuid,
            )
            .join(Match, Match.match_uuid == ForecastTaskSchedule.match_uuid)
            .where(
                ForecastTaskSchedule.state.in_(
                    (
                        ForecastTaskState.PENDING,
                        ForecastTaskState.ENQUEUED,
                        ForecastTaskState.PROCESSING,
                    )
                )
            )
            .order_by(ForecastTaskSchedule.schedule_time, ForecastTaskSchedule.schedule_uuid)
        )
    ).all()
    active_match_uuids = set(
        await session.scalars(
            select(PredictionVersion.match_uuid).where(
                PredictionVersion.state.in_(
                    (PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)
                )
            )
        )
    )
    pending: list[PendingForecastTask] = []
    for row, revision, match in pending_rows:
        if match.match_uuid in active_match_uuids:
            row.state = ForecastTaskState.SUCCEEDED
            row.completed_at = now
            row.last_error_code = None
            continue
        current = (
            revision.superseded_at is None
            and revision.canonical_status == FixtureStatus.SCHEDULED
            and match.status == FixtureStatus.SCHEDULED
            and match.identity_review_state == IdentityReviewState.RESOLVED
            and match.kickoff_precision == KickoffPrecision.EXACT
            and match.current_kickoff_at == revision.kickoff_at
            and match.prediction_due_at == row.schedule_time
        )
        if not current:
            row.state = ForecastTaskState.STALE
            row.completed_at = now
            row.last_error_code = "schedule_revision_stale"
            job = await session.scalar(
                select(JobRun)
                .where(
                    JobRun.idempotency_key
                    == (f"{GENERATE_PREDICTION_JOB}:{match.match_uuid}:{revision.revision_number}")
                )
                .with_for_update()
            )
            if job is not None and job.status in (
                JobStatus.PENDING,
                JobStatus.LEASED,
                JobStatus.RUNNING,
            ):
                job.status = JobStatus.CANCELLED
                job.finished_at = now
                job.lease_owner = None
                job.lease_expires_at = None
            continue
        if row.state != ForecastTaskState.PENDING:
            continue
        pending.append(
            PendingForecastTask(
                schedule_uuid=row.schedule_uuid,
                task_id=row.task_id,
                schedule_time=row.schedule_time,
                payload=ForecastTaskPayload(
                    match_uuid=row.match_uuid,
                    schedule_revision_uuid=row.schedule_revision_uuid,
                    revision_number=revision.revision_number,
                ),
            )
        )
    await session.flush()
    return tuple(pending)


async def sync_forecast_tasks(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    now: datetime,
    gateway: ForecastTaskGateway | None = None,
    snapshot_gateway: SnapshotTaskGateway | None = None,
    monitor_gateway: MonitorTaskGateway | None = None,
) -> ForecastTaskSyncSummary:
    """Reserve then enqueue tasks; retries heal crashes after external creation."""

    if not settings.forecast_task_scheduling_enabled:
        return ForecastTaskSyncSummary(0, 0, 0, 0, disabled=True)
    resolved_gateway = gateway or GoogleForecastTaskGateway(settings)
    resolved_monitor_gateway = monitor_gateway
    if resolved_monitor_gateway is None:
        if isinstance(resolved_gateway, GoogleForecastTaskGateway):
            resolved_monitor_gateway = resolved_gateway
        else:
            raise ValueError("a monitor gateway is required with a custom forecast gateway")
    resolved_snapshot_gateway = snapshot_gateway
    if settings.public_snapshot_store != "disabled" and resolved_snapshot_gateway is None:
        if isinstance(resolved_gateway, GoogleForecastTaskGateway):
            resolved_snapshot_gateway = resolved_gateway
        else:
            resolved_snapshot_gateway = GoogleForecastTaskGateway(settings)
    horizon = timedelta(days=settings.forecast_task_horizon_days) - timedelta(
        seconds=settings.forecast_task_horizon_safety_seconds
    )
    async with session_factory() as session:
        pending = await reserve_forecast_tasks(
            session,
            now=now,
            horizon=horizon,
            overdue_grace=timedelta(seconds=settings.forecast_monitoring_grace_seconds),
        )
        await session.commit()

    enqueued = already_existed = failed = 0
    for task in pending:
        try:
            await resolved_monitor_gateway.create_monitor(
                PendingMonitorTask(
                    task_id=monitor_task_id(task.payload.schedule_revision_uuid),
                    schedule_time=max(
                        task.schedule_time
                        + timedelta(seconds=settings.forecast_monitoring_grace_seconds),
                        now + timedelta(seconds=30),
                    ),
                    payload=ForecastMonitoringPayload(
                        match_uuid=task.payload.match_uuid,
                        schedule_revision_uuid=task.payload.schedule_revision_uuid,
                    ),
                )
            )
            if resolved_snapshot_gateway is not None:
                await resolved_snapshot_gateway.create_snapshot(
                    PendingSnapshotTask(
                        task_id=snapshot_task_id(task.payload.schedule_revision_uuid),
                        schedule_time=task.schedule_time
                        + timedelta(seconds=settings.simulation_presentation_seconds),
                        payload=SnapshotFinalizationPayload(
                            match_uuid=task.payload.match_uuid,
                            schedule_revision_uuid=task.payload.schedule_revision_uuid,
                        ),
                    )
                )
            cloud_name, existed = await resolved_gateway.create(task)
            async with session_factory() as session:
                row = await session.scalar(
                    select(ForecastTaskSchedule)
                    .where(ForecastTaskSchedule.schedule_uuid == task.schedule_uuid)
                    .with_for_update()
                )
                if row is not None and row.state == ForecastTaskState.PENDING:
                    row.state = ForecastTaskState.ENQUEUED
                    row.cloud_task_name = cloud_name
                    row.enqueued_at = now
                    row.last_error_code = None
                await session.commit()
            enqueued += 1
            already_existed += int(existed)
        except Exception:
            failed += 1
            logger.exception(
                "forecast_task_enqueue_failed",
                schedule_uuid=str(task.schedule_uuid),
                error_code="cloud_task_create_failed",
            )
            async with session_factory() as session:
                row = await session.get(ForecastTaskSchedule, task.schedule_uuid)
                if row is not None and row.state == ForecastTaskState.PENDING:
                    row.last_error_code = "cloud_task_create_failed"
                await session.commit()
    return ForecastTaskSyncSummary(len(pending), enqueued, already_existed, failed)
