"""Versioned Elo model and evaluation artifact persistence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import joblib  # type: ignore[import-untyped]

from prem_engine_modeling.data import HistoricalDataset
from prem_engine_modeling.elo import EloConfig, EloModel
from prem_engine_modeling.evaluation import EvaluationMetrics
from prem_engine_modeling.training import BaselineTrainingResult

ARTIFACT_SCHEMA_VERSION = "elo-baseline-artifact-v1"


@dataclass(frozen=True)
class WrittenArtifacts:
    model_version: str
    model_path: Path
    model_checksum: str
    report_path: Path
    report_checksum: str


def _metrics_dict(metrics: EvaluationMetrics) -> dict[str, Any]:
    return asdict(metrics)


def model_version(dataset: HistoricalDataset, config: EloConfig) -> str:
    identity = {
        "artifact_schema": ARTIFACT_SCHEMA_VERSION,
        "dataset_checksum": dataset.checksum,
        "config": asdict(config),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"elo-v1-{digest[:12]}"


def training_summary(
    result: BaselineTrainingResult,
    dataset: HistoricalDataset,
    *,
    version: str,
) -> dict[str, Any]:
    return {
        "contract_version": "elo-baseline-summary-v1",
        "model_version": version,
        "model_type": "three_outcome_davidson_elo",
        "deterministic": True,
        "dataset_checksum": dataset.checksum,
        "dataset_rows": len(dataset.records),
        "seasons": list(dataset.seasons),
        "split": asdict(result.split),
        "parameter_candidates": result.tuning.candidate_count,
        "selected_config": asdict(result.tuning.selected_config),
        "validation_metrics": _metrics_dict(result.tuning.validation_metrics),
        "holdout_metrics": _metrics_dict(result.elo_test_metrics),
        "holdout_metrics_by_season": {
            season: _metrics_dict(metrics)
            for season, metrics in result.elo_test_metrics_by_season.items()
        },
        "empirical_baseline_probabilities": asdict(result.empirical_baseline_probabilities),
        "empirical_baseline_metrics": _metrics_dict(result.empirical_baseline_metrics),
        "uniform_baseline_metrics": _metrics_dict(result.uniform_baseline_metrics),
        "goal_metrics": {
            "status": "not_applicable",
            "reason": "The Phase 6 Elo baseline predicts match results, not goal counts.",
        },
        "feature_policy": {
            "features": ["pre_match_home_rating", "pre_match_away_rating", "home_advantage"],
            "outcome_update_rule": "available_after < next_fixture_kickoff",
            "betting_odds_used": False,
            "post_match_statistics_used": False,
        },
    }


def write_training_artifacts(
    result: BaselineTrainingResult,
    dataset: HistoricalDataset,
    *,
    artifact_root: Path,
    created_at: datetime | None = None,
) -> WrittenArtifacts:
    """Write one immutable inference payload and its full evaluation report."""

    version = model_version(dataset, result.tuning.selected_config)
    destination = artifact_root / version
    destination.mkdir(parents=True, exist_ok=True)
    model_path = destination / "model.joblib"
    report_path = destination / "evaluation.json"
    if model_path.exists() or report_path.exists():
        raise FileExistsError(f"artifact version already exists: {version}")

    club_names: dict[str, str] = {}
    for record in dataset.records:
        club_names[record.home_club_uuid] = record.home_club
        club_names[record.away_club_uuid] = record.away_club
    payload: dict[str, Any] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_version": version,
        "model_type": "three_outcome_davidson_elo",
        "dataset_checksum": dataset.checksum,
        "trained_through": max(record.available_after for record in dataset.records).isoformat(),
        "current_season": dataset.seasons[-1],
        "config": asdict(result.tuning.selected_config),
        "ratings": result.final_ratings,
        "club_names": dict(sorted(club_names.items())),
    }
    joblib.dump(payload, model_path, compress=3)
    model_body = model_path.read_bytes()
    model_checksum = hashlib.sha256(model_body).hexdigest()

    report = training_summary(result, dataset, version=version)
    report.update(
        {
            "created_at": (created_at or datetime.now(UTC)).isoformat(),
            "model_artifact": {
                "path": model_path.as_posix(),
                "sha256": model_checksum,
            },
        }
    )
    report_body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(report_body)
    return WrittenArtifacts(
        model_version=version,
        model_path=model_path,
        model_checksum=model_checksum,
        report_path=report_path,
        report_checksum=hashlib.sha256(report_body).hexdigest(),
    )


def load_elo_artifact(path: Path) -> EloModel:
    """Load and validate the inference subset of a trusted local model artifact."""

    loaded = joblib.load(path)
    if not isinstance(loaded, dict):
        raise ValueError("Elo artifact must contain a mapping")
    payload = cast(dict[str, Any], loaded)
    if payload.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported Elo artifact schema")
    config_values = payload.get("config")
    ratings_values = payload.get("ratings")
    current_season = payload.get("current_season")
    if not isinstance(config_values, dict) or not isinstance(ratings_values, dict):
        raise ValueError("Elo artifact is missing config or ratings")
    if not isinstance(current_season, str):
        raise ValueError("Elo artifact is missing its current season")
    config = EloConfig(**cast(dict[str, float], config_values))
    ratings = {str(key): float(value) for key, value in ratings_values.items()}
    return EloModel.from_snapshot(
        config=config,
        ratings=ratings,
        current_season=current_season,
    )
