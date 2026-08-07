"""Tune, evaluate, and persist the deterministic Phase 6 Elo baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prem_engine_modeling.artifacts import training_summary, write_training_artifacts
from prem_engine_modeling.data import load_historical_dataset
from prem_engine_modeling.training import ParameterGrid, train_baseline

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
        default=PROJECT_ROOT / "artifacts" / "models" / "elo",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_historical_dataset(args.dataset)
    result = train_baseline(dataset, parameter_grid=ParameterGrid())
    artifacts = write_training_artifacts(
        result,
        dataset,
        artifact_root=args.artifact_root,
    )
    output = training_summary(result, dataset, version=artifacts.model_version)
    output["artifacts"] = {
        "model_path": artifacts.model_path.as_posix(),
        "model_checksum": artifacts.model_checksum,
        "report_path": artifacts.report_path.as_posix(),
        "report_checksum": artifacts.report_checksum,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
