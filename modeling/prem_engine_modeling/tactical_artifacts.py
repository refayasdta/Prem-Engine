"""Immutable Phase 15 tactical candidate artifacts."""

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

from prem_engine_modeling.tabular_artifacts import tabular_training_summary
from prem_engine_modeling.tabular_data import CLASS_ORDER
from prem_engine_modeling.tabular_training import (
    TabularTrainingResult,
    calibrated_predict_proba,
)
from prem_engine_modeling.tactical_training import TacticalTrainingDataset

TACTICAL_ARTIFACT_SCHEMA_VERSION = "tactical-model-artifact-v1"


@dataclass(frozen=True)
class WrittenTacticalArtifacts:
    model_version: str
    model_path: Path
    model_checksum: str
    report_path: Path
    report_checksum: str


@dataclass(frozen=True)
class TacticalPredictor:
    pipeline: Any
    temperature: float
    feature_columns: tuple[str, ...]
    promotion_status: str

    def predict_proba(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        if features.ndim != 2 or features.shape[1] != len(self.feature_columns):
            raise ValueError("inference matrix does not match the tactical feature contract")
        return calibrated_predict_proba(self.pipeline, features, temperature=self.temperature)


def tactical_model_version(dataset: TacticalTrainingDataset, result: TabularTrainingResult) -> str:
    identity = {
        "artifact_schema": TACTICAL_ARTIFACT_SCHEMA_VERSION,
        "feature_dataset_checksum": dataset.tabular.checksum,
        "source_checksums": (
            dataset.player_feature_checksum,
            dataset.historical_match_checksum,
            dataset.player_context_checksum,
        ),
        "feature_columns": dataset.tabular.feature_columns,
        "candidate": asdict(result.selected_candidate),
        "temperature": result.calibration_temperature,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"tactical-v1-{digest[:12]}"


def tactical_training_summary(
    result: TabularTrainingResult,
    dataset: TacticalTrainingDataset,
    *,
    version: str,
) -> dict[str, Any]:
    summary = tabular_training_summary(result, dataset.tabular, version=version)
    summary.update(
        {
            "contract_version": "tactical-training-summary-v1",
            "coverage_gate": asdict(dataset.coverage),
            "player_feature_checksum": dataset.player_feature_checksum,
            "historical_match_checksum": dataset.historical_match_checksum,
            "player_context_checksum": dataset.player_context_checksum,
            "limitations": [
                "Formation is a position-group shape inferred from observed starters.",
                "FPL position groups do not reveal in-possession or out-of-possession structures.",
                "Shot, corner, and foul patterns are measurable proxies, not subjective labels.",
                "Feature influence is associational and is not evidence of causation.",
            ],
        }
    )
    return summary


def write_tactical_artifacts(
    result: TabularTrainingResult,
    dataset: TacticalTrainingDataset,
    *,
    artifact_root: Path,
    created_at: datetime | None = None,
) -> WrittenTacticalArtifacts:
    version = tactical_model_version(dataset, result)
    destination = artifact_root / version
    destination.mkdir(parents=True, exist_ok=True)
    model_path = destination / "model.joblib"
    report_path = destination / "evaluation.json"
    if model_path.exists() or report_path.exists():
        raise FileExistsError(f"artifact version already exists: {version}")
    payload: dict[str, Any] = {
        "schema_version": TACTICAL_ARTIFACT_SCHEMA_VERSION,
        "model_version": version,
        "model_type": result.selected_candidate.family,
        "feature_dataset_checksum": dataset.tabular.checksum,
        "feature_columns": dataset.tabular.feature_columns,
        "class_order": CLASS_ORDER,
        "candidate": asdict(result.selected_candidate),
        "temperature": result.calibration_temperature,
        "base_training_seasons": dataset.tabular.split.base_training_seasons,
        "calibration_season": dataset.tabular.split.calibration_season,
        "promotion_status": result.promotion.status,
        "approved_for_official_forecasts": result.promotion.status == "promoted",
        "pipeline": result.fitted_pipeline,
    }
    joblib.dump(payload, model_path, compress=3)
    model_checksum = hashlib.sha256(model_path.read_bytes()).hexdigest()
    report = tactical_training_summary(result, dataset, version=version)
    report.update(
        {
            "created_at": (created_at or datetime.now(UTC)).isoformat(),
            "model_artifact": {"path": model_path.as_posix(), "sha256": model_checksum},
        }
    )
    report_body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(report_body)
    return WrittenTacticalArtifacts(
        model_version=version,
        model_path=model_path,
        model_checksum=model_checksum,
        report_path=report_path,
        report_checksum=hashlib.sha256(report_body).hexdigest(),
    )


def load_tactical_artifact(path: Path) -> TacticalPredictor:
    loaded = joblib.load(path)
    if not isinstance(loaded, dict):
        raise ValueError("tactical artifact must contain a mapping")
    payload = cast(dict[str, Any], loaded)
    if payload.get("schema_version") != TACTICAL_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported tactical artifact schema")
    pipeline = payload.get("pipeline")
    temperature = payload.get("temperature")
    columns = payload.get("feature_columns")
    status = payload.get("promotion_status")
    if pipeline is None or not isinstance(temperature, (float, int)):
        raise ValueError("tactical artifact is missing its pipeline or temperature")
    if (
        not isinstance(columns, (tuple, list))
        or tuple(payload.get("class_order", ())) != CLASS_ORDER
    ):
        raise ValueError("tactical artifact has an invalid feature or class contract")
    if status not in ("promoted", "ensemble_candidate", "rejected"):
        raise ValueError("tactical artifact has an invalid promotion status")
    return TacticalPredictor(
        pipeline=pipeline,
        temperature=float(temperature),
        feature_columns=tuple(str(column) for column in columns),
        promotion_status=str(status),
    )
