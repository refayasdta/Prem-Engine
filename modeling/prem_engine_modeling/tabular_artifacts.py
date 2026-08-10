"""Immutable Phase 9 tabular artifacts and complete evaluation summaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import joblib  # type: ignore[import-untyped]
import numpy as np
from numpy.typing import NDArray

from prem_engine_modeling.evaluation import EvaluationMetrics
from prem_engine_modeling.tabular_data import CLASS_ORDER, TabularDataset
from prem_engine_modeling.tabular_training import (
    CandidateSpec,
    TabularTrainingResult,
    calibrated_predict_proba,
)

TABULAR_ARTIFACT_SCHEMA_VERSION = "tabular-result-artifact-v1"


@dataclass(frozen=True)
class WrittenTabularArtifacts:
    model_version: str
    model_path: Path
    model_checksum: str
    report_path: Path
    report_checksum: str


@dataclass(frozen=True)
class TabularPredictor:
    pipeline: Any
    temperature: float
    feature_columns: tuple[str, ...]
    promotion_status: str

    def predict_proba(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        if features.ndim != 2 or features.shape[1] != len(self.feature_columns):
            raise ValueError("inference matrix does not match the artifact feature contract")
        return calibrated_predict_proba(
            self.pipeline,
            features,
            temperature=self.temperature,
        )


def tabular_model_version(
    dataset: TabularDataset,
    spec: CandidateSpec,
    *,
    temperature: float,
) -> str:
    identity = {
        "artifact_schema": TABULAR_ARTIFACT_SCHEMA_VERSION,
        "feature_dataset_checksum": dataset.checksum,
        "feature_columns": dataset.feature_columns,
        "candidate": asdict(spec),
        "temperature": temperature,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"tabular-v1-{digest[:12]}"


def _metrics(metrics: EvaluationMetrics) -> dict[str, Any]:
    return asdict(metrics)


def tabular_training_summary(
    result: TabularTrainingResult,
    dataset: TabularDataset,
    *,
    version: str,
) -> dict[str, Any]:
    return {
        "contract_version": "tabular-training-summary-v1",
        "model_version": version,
        "model_type": result.selected_candidate.family,
        "deterministic": True,
        "random_seed": 42,
        "feature_dataset_checksum": dataset.checksum,
        "feature_contract": {
            "feature_count": len(dataset.feature_columns),
            "feature_columns": list(dataset.feature_columns),
            "identity_columns_used": False,
            "target_columns_used_as_features": False,
        },
        "class_order": list(CLASS_ORDER),
        "split": asdict(dataset.split),
        "candidate_count": len(result.leaderboard),
        "selection_metric": "mean_development_fold_log_loss",
        "selected_candidate": asdict(result.selected_candidate),
        "leaderboard": [
            {
                "candidate": asdict(score.spec),
                "mean_log_loss": score.mean_log_loss,
                "mean_brier_score": score.mean_brier_score,
                "folds": [
                    {
                        "train_seasons": fold.train_seasons,
                        "validation_season": fold.validation_season,
                        "metrics": _metrics(fold.metrics),
                    }
                    for fold in score.fold_scores
                ],
            }
            for score in result.leaderboard
        ],
        "calibration": {
            "method": "single_temperature_scaling",
            "season": dataset.split.calibration_season,
            "temperature": result.calibration_temperature,
            "uncalibrated_metrics": _metrics(result.calibration_uncalibrated_metrics),
            "calibrated_metrics": _metrics(result.calibration_calibrated_metrics),
        },
        "holdout": {
            "uncalibrated_metrics": _metrics(result.holdout_uncalibrated_metrics),
            "calibrated_metrics": _metrics(result.holdout_calibrated_metrics),
            "metrics_by_season": {
                season: _metrics(metrics)
                for season, metrics in result.holdout_metrics_by_season.items()
            },
        },
        "benchmarks": {
            "phase_6_elo": _metrics(result.elo_holdout_metrics),
            "phase_7_goals": _metrics(result.goal_holdout_metrics),
            "historical_prior": _metrics(result.historical_prior_holdout_metrics),
        },
        "feature_influences": [asdict(item) for item in result.feature_influences],
        "promotion": asdict(result.promotion),
        "limitations": [
            "No player strength, injuries, suspensions, transfers, expected lineups, or tactics.",
            "Feature influence is associational and is not evidence of causation.",
            "The dataset contains six Premier League seasons and remains small for complex models.",
        ],
    }


def write_tabular_artifacts(
    result: TabularTrainingResult,
    dataset: TabularDataset,
    *,
    artifact_root: Path,
    created_at: datetime | None = None,
) -> WrittenTabularArtifacts:
    version = tabular_model_version(
        dataset,
        result.selected_candidate,
        temperature=result.calibration_temperature,
    )
    destination = artifact_root / version
    destination.mkdir(parents=True, exist_ok=True)
    model_path = destination / "model.joblib"
    report_path = destination / "evaluation.json"
    if model_path.exists() or report_path.exists():
        raise FileExistsError(f"artifact version already exists: {version}")
    payload: dict[str, Any] = {
        "schema_version": TABULAR_ARTIFACT_SCHEMA_VERSION,
        "model_version": version,
        "model_type": result.selected_candidate.family,
        "feature_dataset_checksum": dataset.checksum,
        "feature_columns": dataset.feature_columns,
        "class_order": CLASS_ORDER,
        "candidate": asdict(result.selected_candidate),
        "temperature": result.calibration_temperature,
        "base_training_seasons": dataset.split.base_training_seasons,
        "calibration_season": dataset.split.calibration_season,
        "promotion_status": result.promotion.status,
        "approved_for_official_forecasts": result.promotion.status == "promoted",
        "pipeline": result.fitted_pipeline,
    }
    joblib.dump(payload, model_path, compress=3)
    model_checksum = hashlib.sha256(model_path.read_bytes()).hexdigest()
    report = tabular_training_summary(result, dataset, version=version)
    report.update(
        {
            "created_at": (created_at or datetime.now(UTC)).isoformat(),
            "model_artifact": {"path": model_path.as_posix(), "sha256": model_checksum},
        }
    )
    report_body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(report_body)
    return WrittenTabularArtifacts(
        model_version=version,
        model_path=model_path,
        model_checksum=model_checksum,
        report_path=report_path,
        report_checksum=hashlib.sha256(report_body).hexdigest(),
    )


def load_tabular_artifact(path: Path) -> TabularPredictor:
    """Load a trusted local Phase 9 inference artifact."""

    loaded = joblib.load(path)
    if not isinstance(loaded, dict):
        raise ValueError("tabular artifact must contain a mapping")
    payload = cast(dict[str, Any], loaded)
    if payload.get("schema_version") != TABULAR_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported tabular artifact schema")
    pipeline = payload.get("pipeline")
    temperature = payload.get("temperature")
    columns = payload.get("feature_columns")
    class_order = payload.get("class_order")
    promotion_status = payload.get("promotion_status")
    if pipeline is None or not isinstance(temperature, (float, int)):
        raise ValueError("tabular artifact is missing its pipeline or temperature")
    if not isinstance(columns, (tuple, list)) or tuple(class_order or ()) != CLASS_ORDER:
        raise ValueError("tabular artifact has an invalid feature or class contract")
    if promotion_status not in ("promoted", "ensemble_candidate", "rejected"):
        raise ValueError("tabular artifact has an invalid promotion status")
    return TabularPredictor(
        pipeline=pipeline,
        temperature=float(temperature),
        feature_columns=tuple(str(column) for column in columns),
        promotion_status=str(promotion_status),
    )
