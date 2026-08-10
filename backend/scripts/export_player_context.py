"""Export canonical Phase 10 player data from PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.player_context import export_player_context


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/processed/player_context"),
    )
    return parser.parse_args()


async def run(output_root: Path) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            result = await export_player_context(session, output_root=output_root)
    finally:
        await engine.dispose()
    print("PREM ENGINE - PLAYER CONTEXT EXPORT")
    print(f"Player performances       {result.performance_count:,}")
    print(f"Availability observations {result.availability_count:,}")
    print(f"Transfer observations     {result.transfer_count:,}")
    print(f"Output directory          {output_root}")
    print(f"Performance SHA-256       {result.performance_checksum}")


def main() -> None:
    args = parse_args()
    asyncio.run(run(args.output_root))


if __name__ == "__main__":
    main()
