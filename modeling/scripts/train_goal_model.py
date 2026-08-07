"""Tune, evaluate, and persist the deterministic Phase 7 goal model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prem_engine_modeling.data import load_historical_dataset
from prem_engine_modeling.goal_artifacts import goal_training_summary, write_goal_artifacts
from prem_engine_modeling.goal_reporting import human_training_report
from prem_engine_modeling.goal_training import GoalParameterGrid, train_goal_model

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "historical_training_matches.csv",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "models" / "goals",
    )
    parser.add_argument(
        "--output-format",
        choices=("human", "json"),
        default="human",
        help="Human-readable terminal summary (default) or machine-readable JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_historical_dataset(args.dataset)
    parameter_grid = GoalParameterGrid()
    if args.output_format == "human":
        print("Phase 7 training started.")
        print(f"Loaded {len(dataset.records):,} matches from {len(dataset.seasons)} seasons.")
        print(
            f"Testing {len(parameter_grid.configurations())} goal-model candidates and "
            "reproducing the Phase 6 benchmark..."
        )
    result = train_goal_model(dataset, parameter_grid=parameter_grid)
    artifacts = write_goal_artifacts(result, dataset, artifact_root=args.artifact_root)
    if args.output_format == "json":
        output = goal_training_summary(result, dataset, version=artifacts.model_version)
        output["artifacts"] = {
            "model_path": artifacts.model_path.as_posix(),
            "model_checksum": artifacts.model_checksum,
            "report_path": artifacts.report_path.as_posix(),
            "report_checksum": artifacts.report_checksum,
        }
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(human_training_report(result, dataset, artifacts))


if __name__ == "__main__":
    main()
