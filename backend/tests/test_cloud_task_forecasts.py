"""Cloud Tasks scheduling and private forecast delivery safety."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import (
    FixtureStatus,
    ForecastTaskState,
    JobStatus,
    PredictionState,
)
from prem_engine_api.domain.models import (
    Club,
    Competition,
    FixtureScheduleRevision,
    ForecastTaskSchedule,
    JobRun,
    Match,
    PredictionVersion,
    Season,
)
from prem_engine_api.forecast_task_app import create_app
from prem_engine_api.scheduling.delivery import (
    ForecastDeliveryResult,
    ForecastMonitoringResult,
    ForecastTaskService,
    SnapshotFinalizationResult,
)
from prem_engine_api.scheduling.forecast_tasks import (
    ForecastMonitoringPayload,
    ForecastTaskPayload,
    GoogleForecastTaskGateway,
    PendingForecastTask,
    PendingMonitorTask,
    PendingSnapshotTask,
    SnapshotFinalizationPayload,
    forecast_task_id,
    monitor_task_id,
    reserve_forecast_tasks,
    snapshot_task_id,
    sync_forecast_tasks,
)
from prem_engine_api.snapshots.publisher import ForecastPublicationMetadata, PublicSnapshotPublisher
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker


async def test_google_task_uses_service_origin_as_oidc_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Any] = []

    class FakeClient:
        @staticmethod
        def queue_path(project: str, location: str, queue: str) -> str:
            return f"projects/{project}/locations/{location}/queues/{queue}"

        @staticmethod
        def task_path(project: str, location: str, queue: str, task: str) -> str:
            return f"projects/{project}/locations/{location}/queues/{queue}/tasks/{task}"

        async def create_task(self, *, request: Any) -> SimpleNamespace:
            captured.append(request)
            return SimpleNamespace(name=request.task.name)

    import prem_engine_api.scheduling.forecast_tasks as task_module

    tasks_module = cast(Any, task_module).tasks_v2
    monkeypatch.setattr(tasks_module, "CloudTasksAsyncClient", FakeClient)
    settings = Settings(
        cloud_tasks_project_id="project",
        cloud_tasks_location="asia-southeast1",
        forecast_task_queue_id="forecast",
        forecast_task_target_url="https://forecast-abc.run.app/tasks/forecast",
        forecast_task_invoker_service_account="tasks@example.iam.gserviceaccount.com",
    )
    gateway = GoogleForecastTaskGateway(settings)
    payload = ForecastTaskPayload(uuid4(), uuid4(), 1)
    pending = PendingForecastTask(
        schedule_uuid=uuid4(),
        task_id=forecast_task_id(payload.match_uuid, 1),
        schedule_time=datetime(2026, 8, 14, tzinfo=UTC),
        payload=payload,
    )

    name, existed = await gateway.create(pending)

    request = captured[0].task
    assert name.endswith(pending.task_id)
    assert existed is False
    assert request.http_request.url.endswith("/tasks/forecast")
    assert request.http_request.oidc_token.audience == "https://forecast-abc.run.app"

    monitor_payload = ForecastMonitoringPayload(
        payload.match_uuid,
        payload.schedule_revision_uuid,
    )
    monitor = PendingMonitorTask(
        task_id=monitor_task_id(payload.schedule_revision_uuid),
        schedule_time=pending.schedule_time + timedelta(minutes=10),
        payload=monitor_payload,
    )
    await gateway.create_monitor(monitor)
    monitor_request = captured[1].task
    assert monitor_request.http_request.url.endswith("/tasks/monitor")
    assert str(payload.schedule_revision_uuid).encode() in monitor_request.http_request.body

    snapshot_payload = SnapshotFinalizationPayload(
        payload.match_uuid,
        payload.schedule_revision_uuid,
    )
    snapshot = PendingSnapshotTask(
        task_id=snapshot_task_id(payload.schedule_revision_uuid),
        schedule_time=pending.schedule_time + timedelta(seconds=60),
        payload=snapshot_payload,
    )
    await gateway.create_snapshot(snapshot)
    finalizer_request = captured[2].task
    assert finalizer_request.http_request.url.endswith("/tasks/snapshot")
    assert b"prediction_version_uuid" not in finalizer_request.http_request.body
    assert str(payload.schedule_revision_uuid).encode() in finalizer_request.http_request.body


async def _seed_match(
    session: AsyncSession,
    *,
    now: datetime,
) -> tuple[Match, FixtureScheduleRevision]:
    competition = Competition(slug="cloud-tasks", name="Premier League", country_code="GB")
    home = Club(canonical_name="Task Home", short_name="TH")
    away = Club(canonical_name="Task Away", short_name="TA")
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
    kickoff = now + timedelta(days=1, hours=24)
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
    revision = FixtureScheduleRevision(
        match_uuid=match.match_uuid,
        revision_number=1,
        kickoff_at=kickoff,
        canonical_status=FixtureStatus.SCHEDULED,
        provider_status="NS",
        observed_at=now,
    )
    session.add(revision)
    await session.flush()
    return match, revision


async def test_reserving_current_revision_is_idempotent(db_session: AsyncSession) -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    match, revision = await _seed_match(db_session, now=now)

    first = await reserve_forecast_tasks(
        db_session,
        now=now,
        horizon=timedelta(days=29),
        overdue_grace=timedelta(minutes=10),
    )
    second = await reserve_forecast_tasks(
        db_session,
        now=now,
        horizon=timedelta(days=29),
        overdue_grace=timedelta(minutes=10),
    )

    assert len(first) == len(second) == 1
    assert first[0].task_id == forecast_task_id(match.match_uuid, 1)
    assert first[0].payload.schedule_revision_uuid == revision.revision_uuid
    assert await db_session.scalar(select(func.count()).select_from(ForecastTaskSchedule)) == 1
    ledgers = list(await db_session.scalars(select(ForecastTaskSchedule)))
    jobs = list(await db_session.scalars(select(JobRun)))
    assert len(ledgers) == len(jobs) == 1


async def test_task_sync_pairs_generation_with_reveal_finalization(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    await _seed_match(db_session, now=now)
    connection = cast(AsyncConnection, db_session.bind)

    class FakeGateway:
        def __init__(self) -> None:
            self.forecasts: list[PendingForecastTask] = []
            self.monitors: list[PendingMonitorTask] = []
            self.snapshots: list[PendingSnapshotTask] = []
            self.creation_order: list[str] = []

        async def create(self, task: PendingForecastTask) -> tuple[str, bool]:
            self.creation_order.append("forecast")
            self.forecasts.append(task)
            return task.task_id, False

        async def create_snapshot(self, task: PendingSnapshotTask) -> tuple[str, bool]:
            self.creation_order.append("snapshot")
            self.snapshots.append(task)
            return task.task_id, False

        async def create_monitor(self, task: PendingMonitorTask) -> tuple[str, bool]:
            self.creation_order.append("monitor")
            self.monitors.append(task)
            return task.task_id, False

    gateway = FakeGateway()
    settings = Settings(
        forecast_task_scheduling_enabled=True,
        cloud_tasks_project_id="project",
        cloud_tasks_location="asia-southeast1",
        forecast_task_queue_id="forecast",
        forecast_task_target_url="https://forecast.example/tasks/forecast",
        forecast_task_invoker_service_account="tasks@example.iam.gserviceaccount.com",
        public_snapshot_store="local",
    )

    summary = await sync_forecast_tasks(
        async_sessionmaker(bind=connection, expire_on_commit=False),
        settings=settings,
        now=now,
        gateway=gateway,
        snapshot_gateway=gateway,
        monitor_gateway=gateway,
    )

    assert summary.enqueued == 1
    assert len(gateway.forecasts) == len(gateway.monitors) == len(gateway.snapshots) == 1
    assert gateway.creation_order == ["monitor", "snapshot", "forecast"]
    assert gateway.monitors[0].schedule_time == (
        gateway.forecasts[0].schedule_time + timedelta(minutes=10)
    )
    assert gateway.snapshots[0].schedule_time == (
        gateway.forecasts[0].schedule_time + timedelta(seconds=60)
    )
    assert gateway.snapshots[0].payload.schedule_revision_uuid == (
        gateway.forecasts[0].payload.schedule_revision_uuid
    )


async def test_stale_revision_delivery_is_discarded_and_job_cancelled(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    match, revision = await _seed_match(db_session, now=now)
    (task,) = await reserve_forecast_tasks(
        db_session,
        now=now,
        horizon=timedelta(days=29),
        overdue_grace=timedelta(minutes=10),
    )
    revision.superseded_at = now + timedelta(minutes=1)
    new_kickoff = match.current_kickoff_at + timedelta(hours=2)
    match.current_kickoff_at = new_kickoff
    match.prediction_due_at = new_kickoff - timedelta(hours=24)
    db_session.add(
        FixtureScheduleRevision(
            match_uuid=match.match_uuid,
            revision_number=2,
            kickoff_at=new_kickoff,
            canonical_status=FixtureStatus.SCHEDULED,
            provider_status="NS",
            observed_at=now + timedelta(minutes=1),
        )
    )
    await db_session.flush()
    connection = cast(AsyncConnection, db_session.bind)
    service = ForecastTaskService(
        async_sessionmaker(bind=connection, expire_on_commit=False),
        settings=Settings(),
    )

    result = await service.deliver(
        task.payload,
        task_name=task.task_id,
        retry_count=0,
        now=now + timedelta(minutes=2),
    )

    assert result == ForecastDeliveryResult("stale", 200)
    db_session.expire_all()
    ledger = await db_session.scalar(select(ForecastTaskSchedule))
    job = await db_session.scalar(select(JobRun))
    assert ledger is not None and ledger.state == ForecastTaskState.STALE
    assert job is not None and job.status == JobStatus.CANCELLED


async def test_delivery_before_t24_requests_a_retry(db_session: AsyncSession) -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    await _seed_match(db_session, now=now)
    (task,) = await reserve_forecast_tasks(
        db_session,
        now=now,
        horizon=timedelta(days=29),
        overdue_grace=timedelta(minutes=10),
    )
    connection = cast(AsyncConnection, db_session.bind)
    service = ForecastTaskService(
        async_sessionmaker(bind=connection, expire_on_commit=False),
        settings=Settings(),
    )

    result = await service.deliver(
        task.payload,
        task_name=task.task_id,
        retry_count=0,
        now=now,
    )

    assert result == ForecastDeliveryResult("early", 425)


async def test_monitor_distinguishes_missing_healthy_and_stale_revisions(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    match, revision = await _seed_match(db_session, now=now)
    (task,) = await reserve_forecast_tasks(
        db_session,
        now=now,
        horizon=timedelta(days=29),
        overdue_grace=timedelta(minutes=10),
    )
    connection = cast(AsyncConnection, db_session.bind)
    settings = Settings(forecast_monitoring_grace_seconds=600)
    service = ForecastTaskService(
        async_sessionmaker(bind=connection, expire_on_commit=False),
        settings=settings,
    )
    payload = ForecastMonitoringPayload(
        match_uuid=task.payload.match_uuid,
        schedule_revision_uuid=task.payload.schedule_revision_uuid,
    )

    result = await service.monitor(
        payload,
        task_name=monitor_task_id(payload.schedule_revision_uuid),
        now=task.schedule_time + timedelta(minutes=10),
    )

    assert result == ForecastMonitoringResult("missing", 200)

    db_session.add(
        PredictionVersion(
            match_uuid=match.match_uuid,
            version_number=1,
            state=PredictionState.ACTIVE_LOCKED,
            feature_cutoff_at=match.prediction_due_at,
            model_version="test",
            feature_snapshot_checksum="b" * 64,
            home_win_probability=Decimal("0.40000000"),
            draw_probability=Decimal("0.30000000"),
            away_win_probability=Decimal("0.30000000"),
            expected_home_goals=Decimal("1.5000"),
            expected_away_goals=Decimal("1.2000"),
            statistics_distribution={},
            locked_at=match.prediction_due_at,
        )
    )
    await db_session.flush()
    healthy = await service.monitor(
        payload,
        task_name=monitor_task_id(payload.schedule_revision_uuid),
        now=task.schedule_time + timedelta(minutes=10),
    )
    assert healthy == ForecastMonitoringResult("healthy", 200)

    revision.superseded_at = task.schedule_time
    await db_session.flush()
    stale = await service.monitor(
        payload,
        task_name=monitor_task_id(payload.schedule_revision_uuid),
        now=task.schedule_time + timedelta(minutes=10),
    )
    assert stale == ForecastMonitoringResult("stale", 200)


async def test_snapshot_finalizer_waits_for_actual_reveal_boundary(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    match, revision = await _seed_match(db_session, now=now)
    prediction = PredictionVersion(
        match_uuid=match.match_uuid,
        version_number=1,
        state=PredictionState.ACTIVE_LOCKED,
        feature_cutoff_at=match.prediction_due_at,
        model_version="test",
        feature_snapshot_checksum="a" * 64,
        home_win_probability=Decimal("0.40000000"),
        draw_probability=Decimal("0.30000000"),
        away_win_probability=Decimal("0.30000000"),
        expected_home_goals=Decimal("1.5000"),
        expected_away_goals=Decimal("1.2000"),
        statistics_distribution={},
        locked_at=match.prediction_due_at,
    )
    db_session.add(prediction)
    await db_session.flush()
    delivery_time = match.prediction_due_at + timedelta(seconds=60)
    reveal_at = delivery_time + timedelta(seconds=5)

    class FakePublisher:
        enabled = True

        async def close(self) -> None:
            return

        async def forecast_metadata(self, **_: object) -> ForecastPublicationMetadata:
            return ForecastPublicationMetadata(prediction.prediction_version_uuid, reveal_at)

        publish_forecast = AsyncMock()
        publish_standings = AsyncMock()

    publisher = FakePublisher()
    sleep = AsyncMock()
    import prem_engine_api.scheduling.delivery as delivery_module

    monkeypatch.setattr(delivery_module.asyncio, "sleep", sleep)
    connection = cast(AsyncConnection, db_session.bind)
    service = ForecastTaskService(
        async_sessionmaker(bind=connection, expire_on_commit=False),
        settings=Settings(),
        snapshot_publisher=cast(PublicSnapshotPublisher, publisher),
    )
    payload = SnapshotFinalizationPayload(match.match_uuid, revision.revision_uuid)

    result = await service.finalize_snapshot(
        payload,
        task_name=snapshot_task_id(revision.revision_uuid),
        now=delivery_time,
    )

    assert result == SnapshotFinalizationResult("published", 200)
    sleep.assert_awaited_once_with(5.0)
    publisher.publish_forecast.assert_awaited_once_with(
        match_uuid=match.match_uuid,
        now=reveal_at,
    )
    publisher.publish_standings.assert_awaited_once_with(now=reveal_at)


def test_private_handler_requires_task_binding_headers() -> None:
    settings = Settings(forecast_task_queue_id="prem-engine-staging-forecast")
    service = AsyncMock(spec=ForecastTaskService)
    service.deliver.return_value = ForecastDeliveryResult("stale", 200)
    client = TestClient(create_app(settings=settings, service=cast(ForecastTaskService, service)))
    payload = ForecastTaskPayload(
        match_uuid=uuid4(),
        schedule_revision_uuid=uuid4(),
        revision_number=1,
    )
    body = {
        "match_uuid": str(payload.match_uuid),
        "schedule_revision_uuid": str(payload.schedule_revision_uuid),
        "revision_number": 1,
    }

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.post("/tasks/forecast", json=body).status_code == 403
    response = client.post(
        "/tasks/forecast",
        json=body,
        headers={
            "X-CloudTasks-QueueName": settings.forecast_task_queue_id or "",
            "X-CloudTasks-TaskName": forecast_task_id(payload.match_uuid, 1),
            "X-CloudTasks-TaskRetryCount": "0",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"outcome": "stale"}

    service.finalize_snapshot.return_value = SnapshotFinalizationResult("published", 200)
    service.monitor.return_value = ForecastMonitoringResult("healthy", 200)
    snapshot_revision_uuid = uuid4()
    snapshot_body = {
        "match_uuid": str(payload.match_uuid),
        "schedule_revision_uuid": str(snapshot_revision_uuid),
    }
    assert client.post("/tasks/snapshot", json=snapshot_body).status_code == 403
    snapshot_response = client.post(
        "/tasks/snapshot",
        json=snapshot_body,
        headers={
            "X-CloudTasks-QueueName": settings.forecast_task_queue_id or "",
            "X-CloudTasks-TaskName": snapshot_task_id(snapshot_revision_uuid),
        },
    )
    assert snapshot_response.status_code == 200
    assert snapshot_response.json() == {"outcome": "published"}

    monitor_revision_uuid = uuid4()
    monitor_body = {
        "match_uuid": str(payload.match_uuid),
        "schedule_revision_uuid": str(monitor_revision_uuid),
    }
    assert client.post("/tasks/monitor", json=monitor_body).status_code == 403
    monitor_response = client.post(
        "/tasks/monitor",
        json=monitor_body,
        headers={
            "X-CloudTasks-QueueName": settings.forecast_task_queue_id or "",
            "X-CloudTasks-TaskName": monitor_task_id(monitor_revision_uuid),
        },
    )
    assert monitor_response.status_code == 200
    assert monitor_response.json() == {"outcome": "healthy"}
