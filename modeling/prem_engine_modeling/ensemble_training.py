"""Leakage-aware Phase 11 probability ensemble selection and evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from prem_engine_modeling.elo import ResultProbabilities
from prem_engine_modeling.evaluation import EvaluationMetrics, MatchPrediction, evaluate_predictions
from prem_engine_modeling.features import PREMATCH_FEATURE_COLUMNS
from prem_engine_modeling.tabular_data import CLASS_ORDER, TabularDataset
from prem_engine_modeling.tabular_training import (
    CandidateSpec,
    PromotionVerdict,
    build_candidate_pipeline,
    fit_temperature,
    temperature_scale_probabilities,
)

ComponentName = Literal["elo", "goals", "tabular", "player"]
COMPONENT_ORDER: tuple[ComponentName, ...] = ("elo", "goals", "tabular", "player")
DEFAULT_TABULAR_SPEC = CandidateSpec(
    candidate_id="phase-9-logistic-c-0.03",
    family="multinomial_logistic",
    regularization_c=0.03,
)
DEFAULT_PLAYER_SPEC = CandidateSpec(
    candidate_id="phase-10-logistic-c-0.03",
    family="multinomial_logistic",
    regularization_c=0.03,
)


@dataclass(frozen=True)
class EnsembleCandidateScore:
    weights: tuple[float, float, float, float]
    fold_log_losses: tuple[float, ...]
    fold_brier_scores: tuple[float, ...]
    mean_log_loss: float
    mean_brier_score: float


@dataclass(frozen=True)
class EnsembleTrainingResult:
    selected: EnsembleCandidateScore
    leaderboard: tuple[EnsembleCandidateScore, ...]
    component_temperatures: dict[ComponentName, float]
    calibration_temperature: float
    calibration_uncalibrated_metrics: EvaluationMetrics
    calibration_calibrated_metrics: EvaluationMetrics
    holdout_metrics: EvaluationMetrics
    holdout_metrics_by_season: dict[str, EvaluationMetrics]
    component_holdout_metrics: dict[ComponentName, EvaluationMetrics]
    promotion: PromotionVerdict
    tabular_pipeline: object
    player_pipeline: object
    holdout_probabilities: NDArray[np.float64]


def candidate_weights(step: float = 0.1) -> tuple[tuple[float, float, float, float], ...]:
    """Return deterministic convex weights on a finite simplex grid."""

    if not np.isfinite(step) or step <= 0.0 or step > 1.0:
        raise ValueError("weight step must be finite and in (0, 1]")
    units = round(1.0 / step)
    if not np.isclose(units * step, 1.0, atol=1e-12):
        raise ValueError("weight step must divide one exactly")
    values: list[tuple[float, float, float, float]] = []
    for counts in product(range(units + 1), repeat=len(COMPONENT_ORDER)):
        if sum(counts) == units:
            values.append(
                (counts[0] / units, counts[1] / units, counts[2] / units, counts[3] / units)
            )
    return tuple(sorted(values, reverse=True))


def blend_probabilities(
    probabilities: dict[ComponentName, NDArray[np.float64]],
    weights: tuple[float, float, float, float],
) -> NDArray[np.float64]:
    if set(probabilities) != set(COMPONENT_ORDER):
        raise ValueError("ensemble probabilities do not contain the complete component contract")
    if len(weights) != len(COMPONENT_ORDER) or any(value < 0.0 for value in weights):
        raise ValueError("ensemble weights must be non-negative and complete")
    if not np.isclose(sum(weights), 1.0, atol=1e-12):
        raise ValueError("ensemble weights must sum to one")
    shapes = {probabilities[name].shape for name in COMPONENT_ORDER}
    if len(shapes) != 1 or next(iter(shapes))[1:] != (3,):
        raise ValueError("component probability matrices must share an N x 3 shape")
    weighted = (
        weight * probabilities[name]
        for name, weight in zip(COMPONENT_ORDER, weights, strict=True)
    )
    blended = sum(
        weighted,
        start=np.zeros(next(iter(shapes)), dtype=np.float64),
    )
    if not np.isfinite(blended).all() or np.any(blended < 0.0):
        raise ValueError("ensemble emitted invalid probabilities")
    totals = blended.sum(axis=1)
    if not np.allclose(totals, 1.0, atol=1e-10):
        raise ValueError("ensemble probabilities do not sum to one")
    return np.asarray(blended, dtype=np.float64)


def reweight_scoreline_matrix(
    scorelines: NDArray[np.float64],
    result_probabilities: tuple[float, float, float],
) -> NDArray[np.float64]:
    """Reconcile a Phase 7 score matrix with ensemble H/D/A probabilities."""

    if scorelines.ndim != 2 or scorelines.shape[0] != scorelines.shape[1]:
        raise ValueError("scoreline distribution must be a square matrix")
    if not np.isfinite(scorelines).all() or np.any(scorelines < 0.0):
        raise ValueError("scoreline distribution contains invalid probabilities")
    targets = np.asarray(result_probabilities, dtype=np.float64)
    if np.any(targets < 0.0) or not np.isclose(targets.sum(), 1.0, atol=1e-10):
        raise ValueError("result probabilities must be non-negative and sum to one")
    home_mask = np.fromfunction(lambda home, away: home > away, scorelines.shape, dtype=int)
    draw_mask = np.fromfunction(lambda home, away: home == away, scorelines.shape, dtype=int)
    away_mask = np.fromfunction(lambda home, away: home < away, scorelines.shape, dtype=int)
    adjusted = np.zeros_like(scorelines, dtype=np.float64)
    for mask, target in zip((home_mask, draw_mask, away_mask), targets, strict=True):
        current = float(scorelines[mask].sum())
        if current <= 0.0 and target > 0.0:
            raise ValueError("scoreline distribution has no mass for a required result class")
        if current > 0.0:
            adjusted[mask] = scorelines[mask] * (target / current)
    return adjusted


def _ordered_probabilities(pipeline: object, features: NDArray[np.float64]) -> NDArray[np.float64]:
    raw = np.asarray(pipeline.predict_proba(features), dtype=np.float64)  # type: ignore[attr-defined]
    classes = tuple(int(value) for value in pipeline.classes_)  # type: ignore[attr-defined]
    if set(classes) != {0, 1, 2}:
        raise ValueError("component classifier did not preserve all result classes")
    return np.asarray(raw[:, [classes.index(index) for index in range(3)]], dtype=np.float64)


def _column_probabilities(
    dataset: TabularDataset,
    indices: NDArray[np.int64],
    prefix: str,
) -> NDArray[np.float64]:
    positions = [
        dataset.feature_columns.index(f"{prefix}_{result}_probability")
        for result in ("home", "draw", "away")
    ]
    return np.asarray(dataset.features[indices][:, positions], dtype=np.float64)


def _component_probabilities(
    dataset: TabularDataset,
    train_seasons: tuple[str, ...],
    predict_seasons: tuple[str, ...],
    *,
    tabular_spec: CandidateSpec,
    player_spec: CandidateSpec,
) -> tuple[dict[ComponentName, NDArray[np.float64]], object, object]:
    train_indices = dataset.indices_for(train_seasons)
    predict_indices = dataset.indices_for(predict_seasons)
    base_count = len(PREMATCH_FEATURE_COLUMNS)
    tabular = build_candidate_pipeline(tabular_spec)
    player = build_candidate_pipeline(player_spec)
    tabular.fit(dataset.features[train_indices, :base_count], dataset.targets[train_indices])
    player.fit(dataset.features[train_indices], dataset.targets[train_indices])
    return (
        {
            "elo": _column_probabilities(dataset, predict_indices, "elo"),
            "goals": _column_probabilities(dataset, predict_indices, "goal"),
            "tabular": _ordered_probabilities(
                tabular, dataset.features[predict_indices, :base_count]
            ),
            "player": _ordered_probabilities(player, dataset.features[predict_indices]),
        },
        tabular,
        player,
    )


def _metrics(
    dataset: TabularDataset,
    seasons: tuple[str, ...],
    probabilities: NDArray[np.float64],
) -> EvaluationMetrics:
    indices = dataset.indices_for(seasons)
    if len(indices) != len(probabilities):
        raise ValueError("probability count does not match the requested seasons")
    predictions = tuple(
        MatchPrediction(
            match_uuid=dataset.match_uuids[index],
            season=dataset.seasons_by_row[index],
            kickoff_at=dataset.kickoffs[index],
            actual_result=CLASS_ORDER[int(dataset.targets[index])],
            probabilities=ResultProbabilities(*map(float, row)),
        )
        for index, row in zip(indices, probabilities, strict=True)
    )
    return evaluate_predictions(predictions)


def _promotion_verdict(
    ensemble: EvaluationMetrics,
    goals: EvaluationMetrics,
) -> PromotionVerdict:
    improvement = goals.log_loss - ensemble.log_loss
    if improvement >= 0.005 and ensemble.brier_score < goals.brier_score:
        return PromotionVerdict(
            status="promoted",
            reason="Improved Phase 7 holdout log loss by at least 0.005 and improved Brier score.",
            best_benchmark="Phase 7 goals",
            log_loss_improvement=improvement,
        )
    if improvement > 0.0:
        return PromotionVerdict(
            status="ensemble_candidate",
            reason="Improved log loss, but did not pass the complete promotion margin.",
            best_benchmark="Phase 7 goals",
            log_loss_improvement=improvement,
        )
    return PromotionVerdict(
        status="rejected",
        reason="Did not improve holdout log loss over the Phase 7 goal model.",
        best_benchmark="Phase 7 goals",
        log_loss_improvement=improvement,
    )


def train_ensemble_model(
    dataset: TabularDataset,
    *,
    weight_step: float = 0.1,
    tabular_spec: CandidateSpec = DEFAULT_TABULAR_SPEC,
    player_spec: CandidateSpec = DEFAULT_PLAYER_SPEC,
) -> EnsembleTrainingResult:
    if tuple(dataset.feature_columns[: len(PREMATCH_FEATURE_COLUMNS)]) != PREMATCH_FEATURE_COLUMNS:
        raise ValueError("ensemble dataset does not begin with the Phase 8 feature contract")
    fold_components = [
        _component_probabilities(
            dataset,
            train_seasons,
            (validation_season,),
            tabular_spec=tabular_spec,
            player_spec=player_spec,
        )[0]
        for train_seasons, validation_season in dataset.split.development_folds
    ]
    candidates: list[EnsembleCandidateScore] = []
    for weights in candidate_weights(weight_step):
        fold_metrics = [
            _metrics(dataset, (validation_season,), blend_probabilities(components, weights))
            for components, (_, validation_season) in zip(
                fold_components, dataset.split.development_folds, strict=True
            )
        ]
        candidates.append(
            EnsembleCandidateScore(
                weights=weights,
                fold_log_losses=tuple(item.log_loss for item in fold_metrics),
                fold_brier_scores=tuple(item.brier_score for item in fold_metrics),
                mean_log_loss=float(np.mean([item.log_loss for item in fold_metrics])),
                mean_brier_score=float(np.mean([item.brier_score for item in fold_metrics])),
            )
        )
    leaderboard = tuple(
        sorted(
            candidates,
            key=lambda item: (item.mean_log_loss, item.mean_brier_score, item.weights),
        )
    )
    selected = leaderboard[0]
    calibration_components, _, _ = _component_probabilities(
        dataset,
        dataset.split.base_training_seasons,
        (dataset.split.calibration_season,),
        tabular_spec=tabular_spec,
        player_spec=player_spec,
    )
    calibration_indices = dataset.indices_for((dataset.split.calibration_season,))
    component_temperatures: dict[ComponentName, float] = {
        "elo": 1.0,
        "goals": 1.0,
        "tabular": fit_temperature(
            calibration_components["tabular"], dataset.targets[calibration_indices]
        ),
        "player": fit_temperature(
            calibration_components["player"], dataset.targets[calibration_indices]
        ),
    }
    calibrated_components = {
        name: temperature_scale_probabilities(values, component_temperatures[name])
        for name, values in calibration_components.items()
    }
    calibration_raw = blend_probabilities(calibrated_components, selected.weights)
    temperature = fit_temperature(calibration_raw, dataset.targets[calibration_indices])
    calibration_adjusted = temperature_scale_probabilities(calibration_raw, temperature)
    holdout_components, tabular_pipeline, player_pipeline = _component_probabilities(
        dataset,
        dataset.split.base_training_seasons,
        dataset.split.holdout_seasons,
        tabular_spec=tabular_spec,
        player_spec=player_spec,
    )
    holdout_components = {
        name: temperature_scale_probabilities(values, component_temperatures[name])
        for name, values in holdout_components.items()
    }
    holdout = temperature_scale_probabilities(
        blend_probabilities(holdout_components, selected.weights), temperature
    )
    holdout_season_values = np.asarray(dataset.seasons_by_row)[
        dataset.indices_for(dataset.split.holdout_seasons)
    ]
    component_metrics = {
        name: _metrics(dataset, dataset.split.holdout_seasons, values)
        for name, values in holdout_components.items()
    }
    holdout_metrics = _metrics(dataset, dataset.split.holdout_seasons, holdout)
    return EnsembleTrainingResult(
        selected=selected,
        leaderboard=leaderboard,
        component_temperatures=component_temperatures,
        calibration_temperature=temperature,
        calibration_uncalibrated_metrics=_metrics(
            dataset, (dataset.split.calibration_season,), calibration_raw
        ),
        calibration_calibrated_metrics=_metrics(
            dataset, (dataset.split.calibration_season,), calibration_adjusted
        ),
        holdout_metrics=holdout_metrics,
        holdout_metrics_by_season={
            season: _metrics(
                dataset,
                (season,),
                holdout[np.asarray(holdout_season_values == season, dtype=bool)],
            )
            for season in dataset.split.holdout_seasons
        },
        component_holdout_metrics=component_metrics,
        promotion=_promotion_verdict(holdout_metrics, component_metrics["goals"]),
        tabular_pipeline=tabular_pipeline,
        player_pipeline=player_pipeline,
        holdout_probabilities=holdout,
    )
