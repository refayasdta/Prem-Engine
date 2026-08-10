"""Select, calibrate, evaluate, and persist the Phase 9 tabular model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prem_engine_modeling.tabular_artifacts import (
    tabular_training_summary,
    write_tabular_artifacts,
)
from prem_engine_modeling.tabular_data import load_tabular_dataset
from prem_engine_modeling.tabular_reporting import human_tabular_report
from prem_engine_modeling.tabular_training import CandidateGrid, train_tabular_model

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "prematch_features.csv",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "models" / "tabular",
    )
    parser.add_argument(
        "--output-format",
        choices=("human", "json"),
        default="human",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_tabular_dataset(args.dataset)
    grid = CandidateGrid()
    if args.output_format == "human":
        print("Phase 9 tabular training started.")
        print(
            f"Validated {len(dataset.targets):,} fixtures and "
            f"{len(dataset.feature_columns)} approved features."
        )
        print(
            f"Evaluating {len(grid.candidates())} candidates on two chronological folds, "
            "then calibrating on 2023/24..."
        )
    result = train_tabular_model(dataset, candidate_grid=grid)
    artifacts = write_tabular_artifacts(result, dataset, artifact_root=args.artifact_root)
    if args.output_format == "human":
        print(human_tabular_report(result, dataset, artifacts))
    else:
        output = tabular_training_summary(result, dataset, version=artifacts.model_version)
        output["artifacts"] = {
            "model_path": artifacts.model_path.as_posix(),
            "model_checksum": artifacts.model_checksum,
            "report_path": artifacts.report_path.as_posix(),
            "report_checksum": artifacts.report_checksum,
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
