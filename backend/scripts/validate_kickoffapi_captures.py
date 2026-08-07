"""Validate the latest audited probe captures without making network requests."""

from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path

from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.domain.models import RawFetch
from prem_engine_api.providers.kickoffapi.contracts import validate_endpoint_payload
from sqlalchemy import select

PROBE_ENDPOINTS = {"/api/v2/leagues", "/api/v2/teams", "/api/v2/fixtures"}
SUMMARY_PATH = Path("data/contracts/kickoffapi/probe-summary.json")


async def validate_latest_captures() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            captures = list(
                await session.scalars(
                    select(RawFetch)
                    .where(RawFetch.endpoint.in_(PROBE_ENDPOINTS))
                    .order_by(RawFetch.fetched_at.desc())
                    .limit(3)
                )
            )
        if {capture.endpoint for capture in captures} != PROBE_ENDPOINTS:
            raise RuntimeError("the latest captures do not cover all three probe endpoints")
        for capture in captures:
            compressed = (settings.raw_data_root / capture.object_key).read_bytes()
            payload = json.loads(gzip.decompress(compressed))
            validate_endpoint_payload(capture.endpoint, payload)
            print(f"Validated {capture.endpoint}")
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        for probe in summary["probes"]:
            if probe["endpoint"] in PROBE_ENDPOINTS:
                probe["contract_valid"] = True
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(validate_latest_captures())


if __name__ == "__main__":
    main()
