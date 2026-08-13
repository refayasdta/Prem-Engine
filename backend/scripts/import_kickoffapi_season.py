"""Import one complete KickoffAPI fixture season through audited cursor pagination."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import structlog
from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.ingestion.fixtures import FixtureIngestionSummary, FixtureIngestor
from prem_engine_api.observability import configure_observability
from prem_engine_api.providers.kickoffapi.client import KickoffApiClient
from prem_engine_api.providers.raw_storage import create_raw_response_store
from prem_engine_api.scheduling.forecast_tasks import (
    ForecastTaskSyncSummary,
    sync_forecast_tasks,
)
from prem_engine_api.snapshots.publisher import PublicSnapshotPublisher

logger = structlog.get_logger()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default="en.1")
    parser.add_argument("--season", type=int, required=True, metavar="YYYY")
    parser.add_argument("--page-size", type=int, default=50, choices=range(1, 51))
    parser.add_argument("--max-pages", type=int, default=20, choices=range(1, 21))
    return parser.parse_args()


def _next_cursor(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    value = meta.get("nextCursor") or meta.get("next_cursor")
    return str(value) if value not in (None, "") else None


def _combine(summaries: list[FixtureIngestionSummary]) -> dict[str, int]:
    fields = ("received", "created", "updated", "unchanged", "pending_review")
    return {field: sum(getattr(summary, field) for summary in summaries) for field in fields}


async def run(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    configure_observability(settings, service="prem-engine-fixture-sync")
    if settings.kickoff_api_key is None:
        raise SystemExit("KICKOFF_API_KEY is not configured; no requests were made")

    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    summaries: list[FixtureIngestionSummary] = []
    request_uuids: list[str] = []
    raw_fetch_uuids: list[str] = []
    raw_store = create_raw_response_store(settings)
    seen_cursors: set[str] = set()
    cursor: str | None = None
    completed = False
    try:
        async with KickoffApiClient(
            settings=settings,
            session_factory=sessions,
            raw_store=raw_store,
        ) as client:
            for _ in range(args.max_pages):
                params: dict[str, str | int | float | bool] = {
                    "league": args.league,
                    "season": args.season,
                    "limit": args.page_size,
                }
                if cursor is not None:
                    params["cursor"] = cursor
                captured = await client.get("/api/v2/fixtures", params=params)
                async with sessions.begin() as session:
                    summary = await FixtureIngestor(session).ingest(captured.payload)
                summaries.append(summary)
                request_uuids.append(str(captured.provider_request_uuid))
                raw_fetch_uuids.append(str(captured.raw_fetch_uuid))

                next_cursor = _next_cursor(captured.payload)
                if next_cursor is None:
                    completed = True
                    break
                if next_cursor in seen_cursors:
                    raise RuntimeError(f"KickoffAPI repeated fixture cursor {next_cursor!r}")
                seen_cursors.add(next_cursor)
                cursor = next_cursor

        if not completed:
            raise RuntimeError(
                f"fixture import exceeded --max-pages={args.max_pages} before pagination ended"
            )
        try:
            task_summary = await sync_forecast_tasks(
                sessions,
                settings=settings,
                now=datetime.now(UTC),
            )
        except Exception:
            logger.exception(
                "forecast_task_enqueue_failed",
                error_code="task_sync_failed_after_ingestion",
            )
            task_summary = ForecastTaskSyncSummary(0, 0, 0, 1)
        publisher = PublicSnapshotPublisher(sessions, settings=settings)
        try:
            snapshot_summary = asdict(await publisher.publish_all(now=datetime.now(UTC)))
        except Exception:
            logger.exception(
                "snapshot_publication_failed",
                error_code="fixture_sync_snapshot_publication_failed",
            )
            snapshot_summary = {"published": 0, "disabled": False, "failed": True}
        finally:
            await publisher.close()
        return {
            "league": args.league,
            "season": args.season,
            "pages": len(summaries),
            "ingestion": _combine(summaries),
            "page_summaries": [asdict(summary) for summary in summaries],
            "provider_request_uuids": request_uuids,
            "raw_fetch_uuids": raw_fetch_uuids,
            "forecast_tasks": asdict(task_summary),
            "public_snapshots": snapshot_summary,
        }
    finally:
        raw_store.close()
        await engine.dispose()


def main() -> None:
    result = asyncio.run(run(parse_args()))
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
