"""Export canonical match artifacts without downloading or importing data."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.historical.export import (
    build_coverage_report,
    export_benchmark_odds,
    export_training_matches,
    write_coverage_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("data/processed"))
    return parser.parse_args()


async def run(output_root: Path) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            training = await export_training_matches(
                session, output_root / "historical_training_matches.csv"
            )
            odds = await export_benchmark_odds(
                session, output_root / "historical_benchmark_odds.csv"
            )
            coverage = write_coverage_report(
                output_root / "historical_coverage.json",
                await build_coverage_report(session),
            )
    finally:
        await engine.dispose()
    print("PREM ENGINE - CANONICAL MODELING EXPORT")
    print(f"Historical match rows      {training.row_count:,}")
    print(f"Benchmark odds rows        {odds.row_count:,}")
    print(f"Training SHA-256           {training.checksum}")
    print(f"Coverage SHA-256           {coverage.checksum}")


def main() -> None:
    args = parse_args()
    asyncio.run(run(args.output_root))


if __name__ == "__main__":
    main()
