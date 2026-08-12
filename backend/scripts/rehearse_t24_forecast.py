"""Run a rollback-only T-24 rehearsal against one canonical non-production match."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from uuid import UUID

from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.operations.t24_rehearsal import rehearse_t24_forecast


async def run(match_uuid: UUID) -> dict[str, object]:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            transaction = await session.begin()
            try:
                report = await rehearse_t24_forecast(
                    session,
                    settings=settings,
                    match_uuid=match_uuid,
                )
            finally:
                await transaction.rollback()
        return {"status": "passed", "rolled_back": True, **asdict(report)}
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-uuid", type=UUID, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.match_uuid)), indent=2, default=str))


if __name__ == "__main__":
    main()
