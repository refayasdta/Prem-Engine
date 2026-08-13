"""Reconcile pending forecast tasks and emit the daily operational snapshot."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime

import structlog
from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.observability import configure_observability
from prem_engine_api.operations.snapshot import collect_operational_snapshot
from prem_engine_api.scheduling.forecast_tasks import sync_forecast_tasks
from prem_engine_api.snapshots.publisher import PublicSnapshotPublisher

logger = structlog.get_logger()


async def run() -> None:
    settings = get_settings()
    configure_observability(settings, service="prem-engine-maintenance")
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    now = datetime.now(UTC)
    try:
        task_summary = await sync_forecast_tasks(sessions, settings=settings, now=now)
        logger.info("forecast_task_sync_complete", **asdict(task_summary))
        publisher = PublicSnapshotPublisher(sessions, settings=settings)
        try:
            publication_summary = await publisher.publish_all(now=now)
            logger.info("public_snapshot_sync_complete", **asdict(publication_summary))
        except Exception:
            logger.exception(
                "snapshot_publication_failed",
                error_code="maintenance_snapshot_publication_failed",
            )
        finally:
            await publisher.close()
        async with sessions() as session:
            snapshot = await collect_operational_snapshot(
                session,
                now=now,
                t24_grace_seconds=settings.forecast_monitoring_grace_seconds,
            )
        logger.info("operational_snapshot", **asdict(snapshot))
        if snapshot.t24_forecasts_missing:
            logger.error("t24_forecast_missing", count=snapshot.t24_forecasts_missing)
        warning_threshold = min(
            settings.kickoff_quota_warning_threshold,
            settings.kickoff_operational_request_limit,
        )
        if snapshot.provider_requests_today >= warning_threshold:
            logger.warning(
                "provider_quota_approaching",
                provider="kickoffapi",
                request_count=snapshot.provider_requests_today,
                operational_limit=settings.kickoff_operational_request_limit,
                hard_limit=settings.kickoff_daily_request_limit,
            )
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
