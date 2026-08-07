"""Download, archive, normalize, and report on recent Premier League seasons."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.historical.client import FootballDataClient
from prem_engine_api.historical.export import (
    build_coverage_report,
    export_benchmark_odds,
    export_training_matches,
    write_coverage_report,
)
from prem_engine_api.historical.service import import_historical_csv
from prem_engine_api.providers.raw_storage import LocalRawResponseStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-season", type=int, default=2020, metavar="YYYY")
    parser.add_argument("--to-season", type=int, default=2025, metavar="YYYY")
    parser.add_argument(
        "--alias-registry",
        type=Path,
        default=PROJECT_ROOT / "data" / "mappings" / "football-data-clubs.csv",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.from_season > args.to_season:
        raise ValueError("--from-season must not be later than --to-season")
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    client = FootballDataClient(base_url=settings.historical_data_base_url)
    raw_store = LocalRawResponseStore(settings.raw_data_root)
    imports: list[dict[str, Any]] = []
    try:
        for start_year in range(args.from_season, args.to_season + 1):
            download = await client.download_season(start_year)
            async with sessions.begin() as session:
                summary = await import_historical_csv(
                    session,
                    body=download.body,
                    source_url=download.source_url,
                    retrieved_at=download.retrieved_at,
                    season_start_year=start_year,
                    alias_registry_path=args.alias_registry,
                    raw_store=raw_store,
                )
            imports.append(asdict(summary))

        async with sessions() as session:
            training = await export_training_matches(
                session, settings.processed_data_root / "historical_training_matches.csv"
            )
            odds = await export_benchmark_odds(
                session, settings.processed_data_root / "historical_benchmark_odds.csv"
            )
            report = await build_coverage_report(session)
            coverage = write_coverage_report(
                settings.processed_data_root / "historical_coverage.json", report
            )
        return {
            "imports": imports,
            "artifacts": {
                "training": asdict(training),
                "benchmark_odds": asdict(odds),
                "coverage": asdict(coverage),
            },
        }
    finally:
        await engine.dispose()


def main() -> None:
    result = asyncio.run(run(parse_args()))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
