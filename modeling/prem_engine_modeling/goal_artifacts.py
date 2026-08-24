"""Immutable Phase 7 goal-model artifacts and evaluation reports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import joblib  # type: ignore[import-untyped]

from prem_engine_modeling.data import HistoricalDataset
from prem_engine_modeling.goal_evaluation import GoalEvaluationMetrics
from prem_engine_modeling.goal_training import GoalTrainingResult
from prem_engine_modeling.goals import DynamicGoalModel, GoalModelConfig

GOAL_ARTIFACT_SCHEMA_VERSION = "goal-model-artifact-v1"


@dataclass(frozen=True)
class WrittenGoalArtifacts:
    model_version: str
    model_path: Path
    model_checksum: str
    report_path: Path
    report_checksum: str


def goal_model_version(dataset: HistoricalDataset, config: GoalModelConfig) -> str:
    identity = {
        "artifact_schema": GOAL_ARTIFACT_SCHEMA_VERSION,
        "dataset_checksum": dataset.checksum,
        "config": asdict(config),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"goals-v1-{digest[:12]}"


def _goal_metrics(metrics: GoalEvaluationMetrics) -> dict[str, Any]:
    return asdict(metrics)


def goal_training_summary(
    result: GoalTrainingResult,
    dataset: HistoricalDataset,
    *,
    version: str,
) -> dict[str, Any]:
    return {
        "contract_version": "goal-model-summary-v1",
        "model_version": version,
        "model_type": "dynamic_poisson_dixon_coles",
        "deterministic": True,
        "dataset_checksum": dataset.checksum,
        "dataset_rows": len(dataset.records),
        "seasons": list(dataset.seasons),
        "split": asdict(result.split),
        "parameter_candidates": result.tuning.candidate_count,
        "selection_metric": "validation_scoreline_log_loss",
        "selected_config": asdict(result.tuning.selected_config),
        "validation_metrics": _goal_metrics(result.tuning.validation_metrics),
        "holdout_metrics": _goal_metrics(result.holdout_metrics),
        "holdout_metrics_by_season": {
            season: _goal_metrics(metrics)
            for season, metrics in result.holdout_metrics_by_season.items()
        },
        "league_average_baseline": {
            "expected_home_goals": result.league_average_home_goals,
            "expected_away_goals": result.league_average_away_goals,
            "metrics": _goal_metrics(result.league_average_metrics),
        },
        "phase_6_elo_benchmark": asdict(result.elo_holdout_metrics),
        "feature_policy": {
            "features": [
                "online_home_attack_strength",
                "online_home_defence_strength",
                "online_away_attack_strength",
                "online_away_defence_strength",
                "home_advantage",
                "season_carryover",
            ],
            "outcome_update_rule": "available_after < next_fixture_kickoff",
            "recent_form": "implicit_in_online_attack_and_defence_updates",
            "betting_odds_used": False,
            "injuries_or_suspensions_used": False,
            "post_match_statistics_used_as_features": False,
        },
        "limitations": [
            "No player availability, injuries, suspensions, transfers, or expected lineups.",
            (
                "Scoreline probabilities beyond the configured score limit are truncated "
                "and renormalized."
            ),
            "Online form is learned from goals only; richer match statistics are not yet inputs.",
        ],
    }


def write_goal_artifacts(
    result: GoalTrainingResult,
    dataset: HistoricalDataset,
    *,
    artifact_root: Path,
    created_at: datetime | None = None,
) -> WrittenGoalArtifacts:
    version = goal_model_version(dataset, result.tuning.selected_config)
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
        "schema_version": GOAL_ARTIFACT_SCHEMA_VERSION,
        "model_version": version,
        "model_type": "dynamic_poisson_dixon_coles",
        "dataset_checksum": dataset.checksum,
        "trained_through": max(record.available_after for record in dataset.records).isoformat(),
        "current_season": dataset.seasons[-1],
        "config": asdict(result.tuning.selected_config),
        "attack": result.final_attack,
        "defence": result.final_defence,
        "club_names": dict(sorted(club_names.items())),
    }
    joblib.dump(payload, model_path, compress=3)
    model_checksum = hashlib.sha256(model_path.read_bytes()).hexdigest()

    report = goal_training_summary(result, dataset, version=version)
    report.update(
        {
            "created_at": (created_at or datetime.now(UTC)).isoformat(),
            "model_artifact": {"path": model_path.as_posix(), "sha256": model_checksum},
        }
    )
    report_body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(report_body)
    return WrittenGoalArtifacts(
        model_version=version,
        model_path=model_path,
        model_checksum=model_checksum,
        report_path=report_path,
        report_checksum=hashlib.sha256(report_body).hexdigest(),
    )


def load_goal_artifact(path: Path) -> DynamicGoalModel:
    """Load a trusted local Phase 7 inference artifact."""

    loaded = joblib.load(path)
    if not isinstance(loaded, dict):
        raise ValueError("goal artifact must contain a mapping")
    payload = cast(dict[str, Any], loaded)
    if payload.get("schema_version") != GOAL_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported goal artifact schema")
    config_values = payload.get("config")
    attack_values = payload.get("attack")
    defence_values = payload.get("defence")
    current_season = payload.get("current_season")
    if not isinstance(config_values, dict):
        raise ValueError("goal artifact is missing its config")
    if not isinstance(attack_values, dict) or not isinstance(defence_values, dict):
        raise ValueError("goal artifact is missing attack or defence strengths")
    if not isinstance(current_season, str):
        raise ValueError("goal artifact is missing its current season")
    return DynamicGoalModel.from_snapshot(
        config=GoalModelConfig(**cast(dict[str, Any], config_values)),
        attack={str(key): float(value) for key, value in attack_values.items()},
        defence={str(key): float(value) for key, value in defence_values.items()},
        current_season=current_season,
        club_names={
            str(key): str(value)
            for key, value in cast(dict[str, Any], payload.get("club_names") or {}).items()
        },
    )
