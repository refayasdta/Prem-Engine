"""Train and evaluate Phase 12 detailed match-statistics models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prem_engine_modeling.match_statistics_artifacts import (
    statistics_training_summary,
    write_statistics_artifacts,
)
from prem_engine_modeling.match_statistics_data import load_detailed_statistics_dataset
from prem_engine_modeling.match_statistics_reporting import human_statistics_report
from prem_engine_modeling.match_statistics_training import (
    CountModelGrid,
    train_detailed_statistics_models,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--features",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "prematch_features.csv",
    )
    parser.add_argument(
        "--historical",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "historical_training_matches.csv",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "models" / "match-statistics",
    )
    parser.add_argument("--output-format", choices=("human", "json"), default="human")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_detailed_statistics_dataset(args.features, args.historical)
    grid = CountModelGrid()
    if args.output_format == "human":
        print("Phase 12 detailed-statistics training started.")
        print(
            f"Validated {len(dataset.tabular.targets):,} fixtures, "
            f"{len(dataset.target_specs)} targets, and complete target coverage."
        )
        print(
            f"Evaluating {len(grid.alpha_values)} regularization candidates "
            "per target chronologically..."
        )
    result = train_detailed_statistics_models(dataset, grid=grid)
    artifacts = write_statistics_artifacts(result, dataset, artifact_root=args.artifact_root)
    if args.output_format == "human":
        print(human_statistics_report(result, dataset, artifacts))
    else:
        output = statistics_training_summary(result, dataset, version=artifacts.model_version)
        output["artifacts"] = {
            "model_path": artifacts.model_path.as_posix(),
            "model_checksum": artifacts.model_checksum,
            "report_path": artifacts.report_path.as_posix(),
            "report_checksum": artifacts.report_checksum,
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
