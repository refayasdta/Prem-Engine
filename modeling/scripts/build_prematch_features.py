"""Build the deterministic Phase 8 pre-match feature export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prem_engine_modeling.data import load_historical_dataset
from prem_engine_modeling.feature_export import (
    feature_quality_summary,
    human_feature_report,
    write_feature_export,
)
from prem_engine_modeling.features import build_prematch_features

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "historical_training_matches.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "prematch_features.csv",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "prematch_features.report.json",
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing export.")
    parser.add_argument(
        "--output-format",
        choices=("human", "json"),
        default="human",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = load_historical_dataset(args.dataset)
    if args.output_format == "human":
        print("Phase 8 feature generation started.")
        print(f"Loaded {len(source.records):,} historical fixtures.")
        print("Replaying every fixture with a strict 24-hour pre-kickoff cutoff...")
    dataset = build_prematch_features(source)
    written = write_feature_export(
        dataset,
        dataset_path=args.output,
        report_path=args.report,
        force=args.force,
    )
    if args.output_format == "human":
        print(human_feature_report(dataset, written))
    else:
        output = feature_quality_summary(dataset, dataset_checksum=written.dataset_checksum)
        output["outputs"] = {
            "dataset_path": written.dataset_path.as_posix(),
            "dataset_checksum": written.dataset_checksum,
            "report_path": written.report_path.as_posix(),
            "report_checksum": written.report_checksum,
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
