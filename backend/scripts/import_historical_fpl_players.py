"""Import audited historical FPL player performances into PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.providers.historical_fpl import (
    HistoricalFplArchive,
    import_historical_fpl_seasons,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/contracts/fpl-historical/coverage-summary.json"),
    )
    parser.add_argument(
        "--club-aliases",
        type=Path,
        default=Path("data/mappings/fpl-clubs.csv"),
    )
    return parser.parse_args()


async def run(*, manifest: Path, club_aliases: Path) -> None:
    settings = get_settings()
    archive = HistoricalFplArchive(
        manifest_path=manifest,
        raw_root=settings.raw_data_root / "historicalfpl",
        base_url=settings.fpl_historical_base_url,
    )
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            result = await import_historical_fpl_seasons(
                session,
                seasons=archive.seasons(),
                alias_registry_path=club_aliases,
            )
            await session.commit()
    finally:
        await engine.dispose()
    print("PREM ENGINE - HISTORICAL FPL PLAYER IMPORT")
    print(f"Seasons processed          {result.seasons_imported:,}")
    print(f"Source files registered    {result.source_files_registered:,}")
    print(f"Fixture references created {result.fixture_references_created:,}")
    print(f"Players created            {result.players_created:,}")
    print(f"Player references created  {result.player_references_created:,}")
    print(f"Performances created       {result.performances_created:,}")
    print(f"Performances reused        {result.performances_reused:,}")
    print(f"Observed start records     {result.observed_start_records:,}")
    print(f"Unknown start records      {result.unknown_start_records:,}")
    print("Model training             NOT RUN")


def main() -> None:
    args = parse_args()
    asyncio.run(run(manifest=args.manifest, club_aliases=args.club_aliases))


if __name__ == "__main__":
    main()
