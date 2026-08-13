"""Immutable Phase 11 ensemble artifacts and evaluation summaries."""

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

from prem_engine_modeling.ensemble_training import (
    COMPONENT_ORDER,
    DEFAULT_PLAYER_SPEC,
    DEFAULT_TABULAR_SPEC,
    ComponentName,
    EnsembleTrainingResult,
    blend_probabilities,
)
from prem_engine_modeling.features import PREMATCH_FEATURE_COLUMNS
from prem_engine_modeling.tabular_data import CLASS_ORDER, TabularDataset
from prem_engine_modeling.tabular_training import temperature_scale_probabilities

ENSEMBLE_ARTIFACT_SCHEMA_VERSION = "ensemble-artifact-v1"


@dataclass(frozen=True)
class WrittenEnsembleArtifacts:
    model_version: str
    model_path: Path
    model_checksum: str
    report_path: Path
    report_checksum: str


@dataclass(frozen=True)
class EnsemblePredictor:
    weights: tuple[float, float, float, float]
    component_temperatures: dict[ComponentName, float]
    temperature: float
    tabular_pipeline: object
    player_pipeline: object
    feature_columns: tuple[str, ...]
    promotion_status: str

    def predict_proba(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        if features.ndim != 2 or features.shape[1] != len(self.feature_columns):
            raise ValueError("inference matrix does not match the ensemble feature contract")
        base_count = len(PREMATCH_FEATURE_COLUMNS)
        positions = {
            prefix: [
                self.feature_columns.index(f"{prefix}_{result}_probability")
                for result in ("home", "draw", "away")
            ]
            for prefix in ("elo", "goal")
        }
        components: dict[ComponentName, NDArray[np.float64]] = {
            "elo": np.asarray(features[:, positions["elo"]], dtype=np.float64),
            "goals": np.asarray(features[:, positions["goal"]], dtype=np.float64),
            "tabular": _ordered_probabilities(self.tabular_pipeline, features[:, :base_count]),
            "player": _ordered_probabilities(self.player_pipeline, features),
        }
        components = {
            name: temperature_scale_probabilities(values, self.component_temperatures[name])
            for name, values in components.items()
        }
        return temperature_scale_probabilities(
            blend_probabilities(components, self.weights), self.temperature
        )


def _ordered_probabilities(pipeline: object, features: NDArray[np.float64]) -> NDArray[np.float64]:
    raw = np.asarray(pipeline.predict_proba(features), dtype=np.float64)  # type: ignore[attr-defined]
    classes = tuple(int(value) for value in pipeline.classes_)  # type: ignore[attr-defined]
    return np.asarray(raw[:, [classes.index(index) for index in range(3)]], dtype=np.float64)


def ensemble_model_version(
    dataset: TabularDataset,
    result: EnsembleTrainingResult,
) -> str:
    identity = {
        "artifact_schema": ENSEMBLE_ARTIFACT_SCHEMA_VERSION,
        "feature_dataset_checksum": dataset.checksum,
        "weights": result.selected.weights,
        "component_temperatures": result.component_temperatures,
        "temperature": result.calibration_temperature,
        "tabular_candidate": asdict(DEFAULT_TABULAR_SPEC),
        "player_candidate": asdict(DEFAULT_PLAYER_SPEC),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"ensemble-v1-{digest[:12]}"


def _metrics(value: Any) -> dict[str, Any]:
    return asdict(value)


def ensemble_training_summary(
    result: EnsembleTrainingResult,
    dataset: TabularDataset,
    *,
    version: str,
) -> dict[str, Any]:
    return {
        "contract_version": "ensemble-training-summary-v1",
        "model_version": version,
        "model_type": "convex_probability_blend",
        "deterministic": True,
        "feature_dataset_checksum": dataset.checksum,
        "class_order": list(CLASS_ORDER),
        "split": asdict(dataset.split),
        "selection": {
            "method": "development_fold_grid_search",
            "metric": "mean_development_fold_log_loss",
            "candidate_count": len(result.leaderboard),
            "weights": dict(zip(COMPONENT_ORDER, result.selected.weights, strict=True)),
            "mean_log_loss": result.selected.mean_log_loss,
            "mean_brier_score": result.selected.mean_brier_score,
        },
        "calibration": {
            "method": "single_temperature_scaling",
            "season": dataset.split.calibration_season,
            "temperature": result.calibration_temperature,
            "uncalibrated_metrics": _metrics(result.calibration_uncalibrated_metrics),
            "calibrated_metrics": _metrics(result.calibration_calibrated_metrics),
        },
        "holdout": {
            "metrics": _metrics(result.holdout_metrics),
            "metrics_by_season": {
                season: _metrics(metrics)
                for season, metrics in result.holdout_metrics_by_season.items()
            },
        },
        "components": {
            name: {
                "weight": result.selected.weights[index],
                "temperature": result.component_temperatures[name],
                "metrics": _metrics(metrics),
            }
            for index, (name, metrics) in enumerate(result.component_holdout_metrics.items())
        },
        "promotion": asdict(result.promotion),
        "approved_for_official_forecasts": result.promotion.status == "promoted",
        "evaluation_disclosure": (
            "Weights were selected on 2021/22 and 2022/23 development folds and calibrated "
            "on 2023/24. The 2024/25 and 2025/26 targets were not used for fitting, but their "
            "benchmark results had been inspected before Phase 11 was designed."
        ),
        "scoreline_reconciliation": "outcome_partition_rescaling",
    }


def write_ensemble_artifacts(
    result: EnsembleTrainingResult,
    dataset: TabularDataset,
    *,
    artifact_root: Path,
    created_at: datetime | None = None,
) -> WrittenEnsembleArtifacts:
    version = ensemble_model_version(dataset, result)
    destination = artifact_root / version
    destination.mkdir(parents=True, exist_ok=True)
    model_path = destination / "model.joblib"
    report_path = destination / "evaluation.json"
    if model_path.exists() or report_path.exists():
        raise FileExistsError(f"artifact version already exists: {version}")
    payload: dict[str, Any] = {
        "schema_version": ENSEMBLE_ARTIFACT_SCHEMA_VERSION,
        "model_version": version,
        "feature_dataset_checksum": dataset.checksum,
        "feature_columns": dataset.feature_columns,
        "class_order": CLASS_ORDER,
        "component_order": COMPONENT_ORDER,
        "weights": result.selected.weights,
        "component_temperatures": result.component_temperatures,
        "temperature": result.calibration_temperature,
        "base_training_seasons": dataset.split.base_training_seasons,
        "calibration_season": dataset.split.calibration_season,
        "promotion_status": result.promotion.status,
        "approved_for_official_forecasts": result.promotion.status == "promoted",
        "tabular_pipeline": result.tabular_pipeline,
        "player_pipeline": result.player_pipeline,
    }
    joblib.dump(payload, model_path, compress=3)
    model_checksum = hashlib.sha256(model_path.read_bytes()).hexdigest()
    report = ensemble_training_summary(result, dataset, version=version)
    report.update(
        {
            "created_at": (created_at or datetime.now(UTC)).isoformat(),
            "model_artifact": {"path": model_path.as_posix(), "sha256": model_checksum},
        }
    )
    body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(body)
    return WrittenEnsembleArtifacts(
        model_version=version,
        model_path=model_path,
        model_checksum=model_checksum,
        report_path=report_path,
        report_checksum=hashlib.sha256(body).hexdigest(),
    )


def load_ensemble_artifact(path: Path) -> EnsemblePredictor:
    loaded = joblib.load(path)
    if not isinstance(loaded, dict):
        raise ValueError("ensemble artifact must contain a mapping")
    payload = cast(dict[str, Any], loaded)
    if payload.get("schema_version") != ENSEMBLE_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported ensemble artifact schema")
    if tuple(payload.get("class_order", ())) != CLASS_ORDER:
        raise ValueError("ensemble artifact has an invalid class contract")
    if tuple(payload.get("component_order", ())) != COMPONENT_ORDER:
        raise ValueError("ensemble artifact has an invalid component contract")
    status = payload.get("promotion_status")
    if status not in ("promoted", "ensemble_candidate", "rejected"):
        raise ValueError("ensemble artifact has an invalid promotion status")
    columns = payload.get("feature_columns")
    weights = payload.get("weights")
    temperature = payload.get("temperature")
    component_temperatures = payload.get("component_temperatures")
    if not isinstance(columns, (tuple, list)) or not isinstance(weights, (tuple, list)):
        raise ValueError("ensemble artifact has an invalid feature or weight contract")
    if not isinstance(temperature, (float, int)):
        raise ValueError("ensemble artifact has no calibration temperature")
    if not isinstance(component_temperatures, dict) or set(component_temperatures) != set(
        COMPONENT_ORDER
    ):
        raise ValueError("ensemble artifact has an invalid component calibration contract")
    return EnsemblePredictor(
        weights=cast(tuple[float, float, float, float], tuple(float(value) for value in weights)),
        component_temperatures={
            cast(ComponentName, name): float(value)
            for name, value in component_temperatures.items()
        },
        temperature=float(temperature),
        tabular_pipeline=payload["tabular_pipeline"],
        player_pipeline=payload["player_pipeline"],
        feature_columns=tuple(str(value) for value in columns),
        promotion_status=str(status),
    )
