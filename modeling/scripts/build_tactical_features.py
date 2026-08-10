"""Build the leakage-safe Phase 15 tactical feature export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prem_engine_modeling.player_data import load_player_context
from prem_engine_modeling.tactical_feature_export import (
    human_tactical_feature_report,
    tactical_quality_summary,
    write_tactical_feature_export,
)
from prem_engine_modeling.tactical_features import build_tactical_features

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    processed = PROJECT_ROOT / "data" / "processed"
    context = processed / "player_context"
    parser.add_argument(
        "--player-features", default=processed / "player_prematch_features.csv", type=Path
    )
    parser.add_argument(
        "--historical-matches", default=processed / "historical_training_matches.csv", type=Path
    )
    parser.add_argument("--performances", default=context / "player_performances.csv", type=Path)
    parser.add_argument(
        "--availability", default=context / "availability_observations.csv", type=Path
    )
    parser.add_argument("--transfers", default=context / "transfer_observations.csv", type=Path)
    parser.add_argument(
        "--dataset", default=processed / "tactical_prematch_features.csv", type=Path
    )
    parser.add_argument("--report", default=processed / "tactical_feature_quality.json", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output-format", choices=("human", "json"), default="human")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    context = load_player_context(
        performances_path=args.performances,
        availability_path=args.availability,
        transfers_path=args.transfers,
    )
    dataset = build_tactical_features(args.player_features, args.historical_matches, context)
    result = write_tactical_feature_export(
        dataset,
        dataset_path=args.dataset,
        report_path=args.report,
        force=args.force,
    )
    if args.output_format == "human":
        print(human_tactical_feature_report(result))
    else:
        summary = tactical_quality_summary(
            dataset,
            dataset_checksum=result.dataset_checksum,
            coverage=result.coverage,
        )
        summary["artifacts"] = {
            "dataset_path": result.dataset_path.as_posix(),
            "dataset_checksum": result.dataset_checksum,
            "report_path": result.report_path.as_posix(),
            "report_checksum": result.report_checksum,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
