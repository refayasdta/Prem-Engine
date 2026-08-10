"""Coverage-gated training for the Phase 10 player-impact model."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from prem_engine_modeling.player_artifacts import (
    player_training_summary,
    write_player_artifacts,
)
from prem_engine_modeling.player_reporting import (
    human_player_blocked_report,
    human_player_training_report,
)
from prem_engine_modeling.player_training import (
    load_player_impact_dataset,
    train_player_impact_model,
)
from prem_engine_modeling.tabular_training import CandidateGrid

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
        default=PROJECT_ROOT / "artifacts" / "models" / "player-impact",
    )
    parser.add_argument("--output-format", choices=("human", "json"), default="human")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_player_impact_dataset(args.dataset, args.quality_report)
    if not dataset.coverage.trainable:
        if args.output_format == "human":
            print(human_player_blocked_report(dataset))
        else:
            print(
                json.dumps(
                    {
                        "contract_version": "player-impact-readiness-v1",
                        "training_status": "blocked",
                        "approved_for_official_forecasts": False,
                        "coverage_gate": asdict(dataset.coverage),
                        "feature_dataset_checksum": dataset.tabular.checksum,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return

    grid = CandidateGrid()
    if args.output_format == "human":
        print("Phase 10 player-impact training started.")
        print(
            f"Validated {len(dataset.tabular.targets):,} fixtures, "
            f"{len(dataset.tabular.feature_columns)} features, and adequate player coverage."
        )
        print(f"Evaluating {len(grid.candidates())} chronological candidates...")
    result = train_player_impact_model(dataset, candidate_grid=grid)
    artifacts = write_player_artifacts(result, dataset, artifact_root=args.artifact_root)
    if args.output_format == "human":
        print(human_player_training_report(result, dataset, artifacts))
    else:
        output = player_training_summary(result, dataset, version=artifacts.model_version)
        output["artifacts"] = {
            "model_path": artifacts.model_path.as_posix(),
            "model_checksum": artifacts.model_checksum,
            "report_path": artifacts.report_path.as_posix(),
            "report_checksum": artifacts.report_checksum,
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
