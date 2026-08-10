"""Build the leakage-safe Phase 10 player-enhanced feature export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prem_engine_modeling.player_data import load_player_context
from prem_engine_modeling.player_feature_export import (
    human_player_feature_report,
    player_quality_summary,
    write_player_feature_export,
)
from prem_engine_modeling.player_features import build_player_enhanced_features

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-features",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "prematch_features.csv",
    )
    context_root = PROJECT_ROOT / "data" / "processed" / "player_context"
    parser.add_argument(
        "--performances",
        type=Path,
        default=context_root / "player_performances.csv",
    )
    parser.add_argument(
        "--availability",
        type=Path,
        default=context_root / "availability_observations.csv",
    )
    parser.add_argument(
        "--transfers",
        type=Path,
        default=context_root / "transfer_observations.csv",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "player_prematch_features.csv",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "player_feature_quality.json",
    )
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
    dataset = build_player_enhanced_features(args.base_features, context)
    result = write_player_feature_export(
        dataset,
        performance_record_count=len(context.performances),
        dataset_path=args.dataset,
        report_path=args.report,
        force=args.force,
    )
    if args.output_format == "human":
        print(human_player_feature_report(result))
    else:
        summary = player_quality_summary(
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
