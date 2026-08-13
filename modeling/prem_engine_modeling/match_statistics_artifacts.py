"""Phase 12 detailed-statistics artifacts and inference contract."""

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

from prem_engine_modeling.match_statistics_data import (
    STATISTIC_TARGETS,
    UNSUPPORTED_TARGETS,
    DetailedStatisticsDataset,
    StatisticTarget,
)
from prem_engine_modeling.match_statistics_training import (
    DetailedStatisticsTrainingResult,
    reconcile_statistic_means,
)

STATISTICS_ARTIFACT_SCHEMA_VERSION = "detailed-statistics-artifact-v1"


@dataclass(frozen=True)
class WrittenStatisticsArtifacts:
    model_version: str
    model_path: Path
    model_checksum: str
    report_path: Path
    report_checksum: str


@dataclass(frozen=True)
class StatisticsPrediction:
    means: dict[str, float]
    intervals_90: dict[str, tuple[float, float]]


@dataclass(frozen=True)
class DetailedStatisticsPredictor:
    feature_columns: tuple[str, ...]
    targets: tuple[StatisticTarget, ...]
    pipelines: tuple[object, ...]
    multipliers: tuple[float, ...]
    residual_quantiles: tuple[float, ...]
    use_model: tuple[bool, ...]
    baseline_means: tuple[float, ...]

    def predict(self, features: NDArray[np.float64]) -> tuple[StatisticsPrediction, ...]:
        if features.ndim != 2 or features.shape[1] != len(self.feature_columns):
            raise ValueError("inference matrix does not match the statistics feature contract")
        columns: list[NDArray[np.float64]] = []
        for pipeline, multiplier, use_model, baseline in zip(
            self.pipelines,
            self.multipliers,
            self.use_model,
            self.baseline_means,
            strict=True,
        ):
            if use_model:
                raw = np.asarray(pipeline.predict(features), dtype=np.float64)  # type: ignore[attr-defined]
                columns.append(np.clip(raw * multiplier, 0.0, None))
            else:
                columns.append(np.full(len(features), baseline, dtype=np.float64))
        matrix = reconcile_statistic_means(np.column_stack(columns), self.targets)
        predictions: list[StatisticsPrediction] = []
        for row in matrix:
            means = {
                target.name: float(value) for target, value in zip(self.targets, row, strict=True)
            }
            intervals = {
                target.name: (
                    max(0.0, float(value) - residual),
                    float(value) + residual,
                )
                for target, value, residual in zip(
                    self.targets, row, self.residual_quantiles, strict=True
                )
            }
            predictions.append(StatisticsPrediction(means=means, intervals_90=intervals))
        return tuple(predictions)


def statistics_model_version(
    result: DetailedStatisticsTrainingResult,
    dataset: DetailedStatisticsDataset,
) -> str:
    identity = {
        "schema": STATISTICS_ARTIFACT_SCHEMA_VERSION,
        "feature_checksum": dataset.tabular.checksum,
        "statistics_checksum": dataset.statistics_checksum,
        "targets": [
            {
                "name": item.target.name,
                "alpha": item.selected_alpha,
                "multiplier": item.calibration_multiplier,
                "use_model": item.use_model,
                "baseline": item.baseline_mean,
            }
            for item in result.targets
        ],
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"detailed-statistics-v1-{digest[:12]}"


def statistics_training_summary(
    result: DetailedStatisticsTrainingResult,
    dataset: DetailedStatisticsDataset,
    *,
    version: str,
) -> dict[str, Any]:
    return {
        "contract_version": "detailed-statistics-training-summary-v1",
        "model_version": version,
        "model_type": "regularized_poisson_per_target",
        "deterministic": True,
        "feature_dataset_checksum": dataset.tabular.checksum,
        "statistics_dataset_checksum": dataset.statistics_checksum,
        "fixture_count": len(dataset.tabular.targets),
        "feature_count": len(dataset.tabular.feature_columns),
        "split": asdict(dataset.tabular.split),
        "target_count": len(result.targets),
        "promoted_target_count": result.promoted_target_count,
        "aggregate_model_mae": result.aggregate_model_mae,
        "aggregate_baseline_mae": result.aggregate_baseline_mae,
        "targets": [
            {
                "name": item.target.name,
                "family": item.target.family,
                "side": item.target.side,
                "source_column": item.target.source_column,
                "selected_alpha": item.selected_alpha,
                "calibration_multiplier": item.calibration_multiplier,
                "residual_quantile_90": item.residual_quantile_90,
                "holdout_metrics": asdict(item.holdout_metrics),
                "baseline_metrics": asdict(item.baseline_metrics),
                "official_source": "model" if item.use_model else "historical_mean_fallback",
                "promotion_reason": item.reason,
                "candidate_scores": [asdict(score) for score in item.leaderboard],
            }
            for item in result.targets
        ],
        "unsupported_targets": UNSUPPORTED_TARGETS,
        "reconciliation": [
            "Predicted shots on target cannot exceed predicted shots for the same team.",
            "All statistic means and interval bounds are non-negative.",
        ],
        "limitations": [
            "Possession and provider-measured xG have no six-season target labels.",
            "Separate count models do not learn cross-statistic event correlation.",
            "Phase 13 must generate one jointly coherent event sequence from these means.",
        ],
    }


def write_statistics_artifacts(
    result: DetailedStatisticsTrainingResult,
    dataset: DetailedStatisticsDataset,
    *,
    artifact_root: Path,
    created_at: datetime | None = None,
) -> WrittenStatisticsArtifacts:
    version = statistics_model_version(result, dataset)
    destination = artifact_root / version
    destination.mkdir(parents=True, exist_ok=True)
    model_path = destination / "model.joblib"
    report_path = destination / "evaluation.json"
    if model_path.exists() or report_path.exists():
        raise FileExistsError(f"artifact version already exists: {version}")
    payload: dict[str, Any] = {
        "schema_version": STATISTICS_ARTIFACT_SCHEMA_VERSION,
        "model_version": version,
        "feature_dataset_checksum": dataset.tabular.checksum,
        "statistics_dataset_checksum": dataset.statistics_checksum,
        "feature_columns": dataset.tabular.feature_columns,
        "targets": dataset.target_specs,
        "pipelines": tuple(item.fitted_pipeline for item in result.targets),
        "multipliers": tuple(item.calibration_multiplier for item in result.targets),
        "residual_quantiles": tuple(item.residual_quantile_90 for item in result.targets),
        "use_model": tuple(item.use_model for item in result.targets),
        "baseline_means": tuple(item.baseline_mean for item in result.targets),
    }
    joblib.dump(payload, model_path, compress=3)
    model_checksum = hashlib.sha256(model_path.read_bytes()).hexdigest()
    report = statistics_training_summary(result, dataset, version=version)
    report.update(
        {
            "created_at": (created_at or datetime.now(UTC)).isoformat(),
            "model_artifact": {"path": model_path.as_posix(), "sha256": model_checksum},
        }
    )
    body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(body)
    return WrittenStatisticsArtifacts(
        model_version=version,
        model_path=model_path,
        model_checksum=model_checksum,
        report_path=report_path,
        report_checksum=hashlib.sha256(body).hexdigest(),
    )


def load_statistics_artifact(path: Path) -> DetailedStatisticsPredictor:
    loaded = joblib.load(path)
    if not isinstance(loaded, dict):
        raise ValueError("statistics artifact must contain a mapping")
    payload = cast(dict[str, Any], loaded)
    if payload.get("schema_version") != STATISTICS_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported statistics artifact schema")
    targets = payload.get("targets")
    if tuple(targets or ()) != STATISTIC_TARGETS:
        raise ValueError("statistics artifact has an invalid target contract")
    columns = payload.get("feature_columns")
    pipelines = payload.get("pipelines")
    multipliers = payload.get("multipliers")
    quantiles = payload.get("residual_quantiles")
    use_model = payload.get("use_model")
    baselines = payload.get("baseline_means")
    if not isinstance(columns, (tuple, list)) or not isinstance(pipelines, (tuple, list)):
        raise ValueError("statistics artifact has an invalid feature or pipeline contract")
    if not all(
        isinstance(value, (tuple, list)) for value in (multipliers, quantiles, use_model, baselines)
    ):
        raise ValueError("statistics artifact has an incomplete inference contract")
    assert isinstance(multipliers, (tuple, list))
    assert isinstance(quantiles, (tuple, list))
    assert isinstance(use_model, (tuple, list))
    assert isinstance(baselines, (tuple, list))
    if any(
        len(value) != len(STATISTIC_TARGETS)
        for value in (pipelines, multipliers, quantiles, use_model, baselines)
    ):
        raise ValueError("statistics artifact target lengths do not agree")
    return DetailedStatisticsPredictor(
        feature_columns=tuple(str(value) for value in columns),
        targets=STATISTIC_TARGETS,
        pipelines=tuple(pipelines),
        multipliers=tuple(float(value) for value in multipliers),
        residual_quantiles=tuple(float(value) for value in quantiles),
        use_model=tuple(bool(value) for value in use_model),
        baseline_means=tuple(float(value) for value in baselines),
    )
