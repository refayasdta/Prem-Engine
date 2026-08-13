"""Private Cloud Run application invoked only by authenticated Cloud Tasks."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, PositiveInt
from sqlalchemy.exc import SQLAlchemyError

from prem_engine_api.config import Settings, get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.observability import RequestLoggingMiddleware, configure_observability
from prem_engine_api.scheduling.delivery import ForecastTaskRejected, ForecastTaskService
from prem_engine_api.scheduling.forecast_tasks import (
    ForecastMonitoringPayload,
    ForecastTaskPayload,
    SnapshotFinalizationPayload,
)


class ForecastTaskRequest(BaseModel):
    match_uuid: UUID
    schedule_revision_uuid: UUID
    revision_number: PositiveInt


class ForecastTaskResponse(BaseModel):
    outcome: Literal["created", "reused", "stale", "duplicate", "early", "busy"]


class SnapshotTaskRequest(BaseModel):
    match_uuid: UUID
    schedule_revision_uuid: UUID


class SnapshotTaskResponse(BaseModel):
    outcome: Literal["published", "stale", "early", "disabled", "busy"]


class MonitorTaskRequest(BaseModel):
    match_uuid: UUID
    schedule_revision_uuid: UUID


class MonitorTaskResponse(BaseModel):
    outcome: Literal["healthy", "missing", "stale", "early"]


def create_app(
    *,
    settings: Settings | None = None,
    service: ForecastTaskService | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    configure_observability(resolved, service="prem-engine-forecast-task")
    engine = None
    resolved_service = service
    owns_service = resolved_service is None
    if resolved_service is None:
        engine = create_engine(resolved)
        resolved_service = ForecastTaskService(create_session_factory(engine), settings=resolved)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if owns_service:
            await resolved_service.close()
        if engine is not None:
            await engine.dispose()

    app = FastAPI(
        title="Prem Engine Forecast Task",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "prem-engine-forecast-task"}

    @app.get("/ready", response_model=None)
    async def ready() -> dict[str, str] | JSONResponse:
        try:
            async with asyncio.timeout(resolved.database_readiness_timeout_seconds):
                await resolved_service.ready()
        except (TimeoutError, SQLAlchemyError):
            return JSONResponse(
                {"status": "unavailable", "service": "prem-engine-forecast-task"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        return {"status": "ready", "service": "prem-engine-forecast-task"}

    @app.post("/tasks/forecast", response_model=None)
    async def forecast_task(
        request: ForecastTaskRequest,
        queue_name: str | None = Header(None, alias="X-CloudTasks-QueueName"),
        task_name: str | None = Header(None, alias="X-CloudTasks-TaskName"),
        retry_count_header: str | None = Header(None, alias="X-CloudTasks-TaskRetryCount"),
    ) -> ForecastTaskResponse | JSONResponse:
        # These headers bind the request to the ledger; Cloud Run IAM plus the
        # configured OIDC token is the caller identity and must remain enforced.
        if queue_name != resolved.forecast_task_queue_id or task_name is None:
            return JSONResponse({"detail": "task delivery rejected"}, status_code=403)
        try:
            retry_count = max(0, int(retry_count_header or "0"))
        except ValueError:
            return JSONResponse({"detail": "task delivery rejected"}, status_code=403)
        try:
            result = await resolved_service.deliver(
                ForecastTaskPayload(
                    match_uuid=request.match_uuid,
                    schedule_revision_uuid=request.schedule_revision_uuid,
                    revision_number=request.revision_number,
                ),
                task_name=task_name,
                retry_count=retry_count,
            )
        except ForecastTaskRejected:
            return JSONResponse({"detail": "task delivery rejected"}, status_code=403)
        body = ForecastTaskResponse(outcome=result.outcome)
        if result.status_code != 200:
            return JSONResponse(body.model_dump(), status_code=result.status_code)
        return body

    @app.post("/tasks/snapshot", response_model=None)
    async def snapshot_task(
        request: SnapshotTaskRequest,
        queue_name: str | None = Header(None, alias="X-CloudTasks-QueueName"),
        task_name: str | None = Header(None, alias="X-CloudTasks-TaskName"),
    ) -> SnapshotTaskResponse | JSONResponse:
        if queue_name != resolved.forecast_task_queue_id or task_name is None:
            return JSONResponse({"detail": "task delivery rejected"}, status_code=403)
        try:
            result = await resolved_service.finalize_snapshot(
                SnapshotFinalizationPayload(
                    match_uuid=request.match_uuid,
                    schedule_revision_uuid=request.schedule_revision_uuid,
                ),
                task_name=task_name,
            )
        except ForecastTaskRejected:
            return JSONResponse({"detail": "task delivery rejected"}, status_code=403)
        body = SnapshotTaskResponse(outcome=result.outcome)
        if result.status_code != 200:
            return JSONResponse(body.model_dump(), status_code=result.status_code)
        return body

    @app.post("/tasks/monitor", response_model=None)
    async def monitor_task(
        request: MonitorTaskRequest,
        queue_name: str | None = Header(None, alias="X-CloudTasks-QueueName"),
        task_name: str | None = Header(None, alias="X-CloudTasks-TaskName"),
    ) -> MonitorTaskResponse | JSONResponse:
        if queue_name != resolved.forecast_task_queue_id or task_name is None:
            return JSONResponse({"detail": "task delivery rejected"}, status_code=403)
        try:
            result = await resolved_service.monitor(
                ForecastMonitoringPayload(
                    match_uuid=request.match_uuid,
                    schedule_revision_uuid=request.schedule_revision_uuid,
                ),
                task_name=task_name,
            )
        except ForecastTaskRejected:
            return JSONResponse({"detail": "task delivery rejected"}, status_code=403)
        body = MonitorTaskResponse(outcome=result.outcome)
        if result.status_code != 200:
            return JSONResponse(body.model_dump(), status_code=result.status_code)
        return body

    return app


app = create_app()
