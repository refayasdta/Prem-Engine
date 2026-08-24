"""Atomically rebuild one season's squad memberships from the latest captured FPL snapshot."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.domain.models import (
    DeviceSimulation,
    RawFetch,
    Season,
    SeasonClub,
    SquadMembership,
)
from prem_engine_api.ingestion.current_fpl import ingest_current_fpl_squads
from prem_engine_api.providers.raw_storage import create_raw_response_store
from sqlalchemy import delete, select


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season-label", required=True, metavar="YYYY/YY")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    raw_store = create_raw_response_store(settings)
    try:
        async with sessions.begin() as session:
            season = await session.scalar(select(Season).where(Season.label == args.season_label))
            if season is None:
                raise SystemExit(f"canonical season not found: {args.season_label}")
            club_uuids = set(
                await session.scalars(
                    select(SeasonClub.club_uuid).where(SeasonClub.season_uuid == season.season_uuid)
                )
            )
            if not club_uuids:
                raise SystemExit(f"season has no clubs: {args.season_label}")
            raw_fetch = await session.scalar(
                select(RawFetch)
                .where(
                    RawFetch.provider == "fpl-current",
                    RawFetch.endpoint == "/api/bootstrap-static/",
                )
                .order_by(RawFetch.fetched_at.desc())
                .limit(1)
            )
            if raw_fetch is None:
                raise SystemExit("no captured FPL bootstrap snapshot is available")
            payload = json.loads(
                raw_store.read(
                    raw_fetch.object_key,
                    expected_checksum=raw_fetch.response_checksum,
                )
            )
            simulations_before = tuple(
                (
                    row.device_simulation_uuid,
                    row.state,
                    row.simulation_checksum,
                )
                for row in await session.scalars(
                    select(DeviceSimulation).order_by(DeviceSimulation.device_simulation_uuid)
                )
            )
            await session.execute(
                delete(SquadMembership).where(SquadMembership.season_uuid == season.season_uuid)
            )
            summary = await ingest_current_fpl_squads(
                session,
                payload,
                season_uuid=season.season_uuid,
                target_club_uuids=club_uuids,
                observed_at=raw_fetch.fetched_at,
            )
            simulations_after = tuple(
                (
                    row.device_simulation_uuid,
                    row.state,
                    row.simulation_checksum,
                )
                for row in await session.scalars(
                    select(DeviceSimulation).order_by(DeviceSimulation.device_simulation_uuid)
                )
            )
            if simulations_after != simulations_before:
                raise RuntimeError("saved simulation preservation check failed")
        return {
            "season": args.season_label,
            "source_object_key": raw_fetch.object_key,
            "saved_simulations_preserved": len(simulations_after),
            "ingestion": asdict(summary),
        }
    finally:
        raw_store.close()
        await engine.dispose()


def main() -> None:
    print(json.dumps(asyncio.run(run(parse_args())), separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
