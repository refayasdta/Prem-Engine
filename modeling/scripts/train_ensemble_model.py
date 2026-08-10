"""Select, calibrate, evaluate, and persist the Phase 11 probability ensemble."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prem_engine_modeling.ensemble_artifacts import (
    ensemble_training_summary,
    write_ensemble_artifacts,
)
from prem_engine_modeling.ensemble_reporting import human_ensemble_report
from prem_engine_modeling.ensemble_training import candidate_weights, train_ensemble_model
from prem_engine_modeling.player_training import load_player_impact_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "player_prematch_features.csv",
    )
    parser.add_argument(
        "--quality-report",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "player_feature_quality.json",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "models" / "ensemble",
    )
    parser.add_argument("--weight-step", type=float, default=0.1)
    parser.add_argument("--output-format", choices=("human", "json"), default="human")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    player_dataset = load_player_impact_dataset(args.dataset, args.quality_report)
    if not player_dataset.coverage.trainable:
        raise RuntimeError(player_dataset.coverage.reason)
    count = len(candidate_weights(args.weight_step))
    if args.output_format == "human":
        print("Phase 11 ensemble training started.")
        print(
            f"Validated {len(player_dataset.tabular.targets):,} fixtures and "
            f"{len(player_dataset.tabular.feature_columns)} features."
        )
        print(f"Evaluating {count} convex weight candidates chronologically...")
    result = train_ensemble_model(player_dataset.tabular, weight_step=args.weight_step)
    artifacts = write_ensemble_artifacts(
        result, player_dataset.tabular, artifact_root=args.artifact_root
    )
    if args.output_format == "human":
        print(human_ensemble_report(result, player_dataset.tabular, artifacts))
    else:
        output = ensemble_training_summary(
            result, player_dataset.tabular, version=artifacts.model_version
        )
        output["artifacts"] = {
            "model_path": artifacts.model_path.as_posix(),
            "model_checksum": artifacts.model_checksum,
            "report_path": artifacts.report_path.as_posix(),
            "report_checksum": artifacts.report_checksum,
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
