"""Run one quota-bounded current player-context synchronization cycle."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.domain.models import CompetitionExternalReference, Season
from prem_engine_api.ingestion.player_sync import sync_player_context
from prem_engine_api.providers.kickoffapi.client import KickoffApiClient
from prem_engine_api.providers.raw_storage import LocalRawResponseStore
from sqlalchemy import select


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default="en.1")
    parser.add_argument("--season", type=int, required=True, metavar="YYYY")
    parser.add_argument("--max-requests", type=int, default=16)
    parser.add_argument("--max-squads", type=int, default=10)
    parser.add_argument("--max-matches", type=int, default=2)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    if settings.kickoff_api_key is None:
        raise SystemExit("KICKOFF_API_KEY is not configured; no requests were made")
    if not 1 <= args.max_requests <= settings.kickoff_operational_request_limit:
        raise SystemExit("--max-requests must fit inside the operational daily allowance")
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            competition_uuid = await session.scalar(
                select(CompetitionExternalReference.competition_uuid).where(
                    CompetitionExternalReference.provider == "kickoffapi",
                    CompetitionExternalReference.external_competition_id == args.league,
                )
            )
            label = f"{args.season}/{str(args.season + 1)[-2:]}"
            season = (
                await session.scalar(
                    select(Season).where(
                        Season.competition_uuid == competition_uuid,
                        Season.label == label,
                    )
                )
                if competition_uuid is not None
                else None
            )
        if season is None:
            raise SystemExit(
                "canonical season not found; import the fixture season before player context"
            )
        async with KickoffApiClient(
            settings=settings,
            session_factory=sessions,
            raw_store=LocalRawResponseStore(settings.raw_data_root),
        ) as client:
            outcome = await sync_player_context(
                client=client,
                session_factory=sessions,
                season_uuid=season.season_uuid,
                league=args.league,
                season=args.season,
                max_requests=args.max_requests,
                max_squads=args.max_squads,
                max_matches=args.max_matches,
            )
        return asdict(outcome)
    finally:
        await engine.dispose()


def main() -> None:
    print(json.dumps(asyncio.run(run(parse_args())), indent=2, default=str))


if __name__ == "__main__":
    main()
