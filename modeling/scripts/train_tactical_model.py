"""Coverage-gated manual training for the Phase 15 tactical model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prem_engine_modeling.tabular_training import CandidateGrid
from prem_engine_modeling.tactical_artifacts import (
    tactical_training_summary,
    write_tactical_artifacts,
)
from prem_engine_modeling.tactical_reporting import (
    human_tactical_blocked_report,
    human_tactical_training_report,
)
from prem_engine_modeling.tactical_training import (
    load_tactical_training_dataset,
    train_tactical_model,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=PROJECT_ROOT / "data" / "processed" / "tactical_prematch_features.csv",
        type=Path,
    )
    parser.add_argument(
        "--quality-report",
        default=PROJECT_ROOT / "data" / "processed" / "tactical_feature_quality.json",
        type=Path,
    )
    parser.add_argument(
        "--artifact-root",
        default=PROJECT_ROOT / "artifacts" / "models" / "tactical",
        type=Path,
    )
    parser.add_argument("--output-format", choices=("human", "json"), default="human")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_tactical_training_dataset(args.dataset, args.quality_report)
    if not dataset.coverage.trainable:
        if args.output_format == "human":
            print(human_tactical_blocked_report(dataset))
        else:
            print(
                json.dumps(
                    {
                        "contract_version": "tactical-readiness-v1",
                        "training_status": "blocked",
                        "approved_for_official_forecasts": False,
                        "coverage_gate": dataset.coverage.__dict__,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return
    grid = CandidateGrid()
    if args.output_format == "human":
        print("Phase 15 tactical training started.")
        print(
            f"Validated {len(dataset.tabular.targets):,} fixtures and "
            f"{len(dataset.tabular.feature_columns)} prior-only features."
        )
        print(f"Evaluating {len(grid.candidates())} chronological candidates...")
    result = train_tactical_model(dataset, candidate_grid=grid)
    artifacts = write_tactical_artifacts(result, dataset, artifact_root=args.artifact_root)
    if args.output_format == "human":
        print(human_tactical_training_report(result, dataset, artifacts))
    else:
        output = tactical_training_summary(result, dataset, version=artifacts.model_version)
        output["artifacts"] = {
            "model_path": artifacts.model_path.as_posix(),
            "model_checksum": artifacts.model_checksum,
            "report_path": artifacts.report_path.as_posix(),
            "report_checksum": artifacts.report_checksum,
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
