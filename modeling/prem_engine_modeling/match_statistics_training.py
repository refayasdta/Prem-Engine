"""Chronological Phase 12 count-model selection, calibration, and evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.linear_model import PoissonRegressor  # type: ignore[import-untyped]
from sklearn.metrics import mean_poisson_deviance  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from prem_engine_modeling.match_statistics_data import (
    DetailedStatisticsDataset,
    StatisticTarget,
)


@dataclass(frozen=True)
class CountModelGrid:
    alpha_values: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0)

    def __post_init__(self) -> None:
        if not self.alpha_values or any(value <= 0.0 for value in self.alpha_values):
            raise ValueError("count-model alphas must be positive")


@dataclass(frozen=True)
class CountMetrics:
    sample_count: int
    mean_actual: float
    mean_prediction: float
    mean_absolute_error: float
    root_mean_squared_error: float
    mean_poisson_deviance: float
    bias: float
    interval_90_coverage: float


@dataclass(frozen=True)
class AlphaScore:
    alpha: float
    fold_deviances: tuple[float, ...]
    mean_deviance: float


@dataclass(frozen=True)
class TargetTrainingResult:
    target: StatisticTarget
    selected_alpha: float
    leaderboard: tuple[AlphaScore, ...]
    calibration_multiplier: float
    residual_quantile_90: float
    holdout_metrics: CountMetrics
    baseline_metrics: CountMetrics
    use_model: bool
    reason: str
    baseline_mean: float
    fitted_pipeline: Any
    holdout_predictions: NDArray[np.float64]


@dataclass(frozen=True)
class DetailedStatisticsTrainingResult:
    targets: tuple[TargetTrainingResult, ...]
    official_holdout_predictions: NDArray[np.float64]
    aggregate_model_mae: float
    aggregate_baseline_mae: float
    promoted_target_count: int


def build_count_pipeline(alpha: float) -> Any:
    if alpha <= 0.0:
        raise ValueError("Poisson regularization alpha must be positive")
    return Pipeline(
        steps=(
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            ("model", PoissonRegressor(alpha=alpha, max_iter=2000, tol=1e-8)),
        )
    )


def _predict(pipeline: Any, features: NDArray[np.float64]) -> NDArray[np.float64]:
    values = np.asarray(pipeline.predict(features), dtype=np.float64)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError("count model emitted invalid predictions")
    return np.asarray(np.clip(values, 1e-6, None), dtype=np.float64)


def _metrics(
    actual: NDArray[np.float64],
    prediction: NDArray[np.float64],
    *,
    residual_quantile_90: float,
) -> CountMetrics:
    errors = prediction - actual
    lower = np.clip(prediction - residual_quantile_90, 0.0, None)
    upper = prediction + residual_quantile_90
    return CountMetrics(
        sample_count=len(actual),
        mean_actual=float(actual.mean()),
        mean_prediction=float(prediction.mean()),
        mean_absolute_error=float(np.abs(errors).mean()),
        root_mean_squared_error=float(np.sqrt(np.square(errors).mean())),
        mean_poisson_deviance=float(
            mean_poisson_deviance(actual, np.clip(prediction, 1e-6, None))
        ),
        bias=float(errors.mean()),
        interval_90_coverage=float(np.mean((actual >= lower) & (actual <= upper))),
    )


def reconcile_statistic_means(
    predictions: NDArray[np.float64],
    targets: tuple[StatisticTarget, ...],
) -> NDArray[np.float64]:
    """Enforce deterministic relationships needed by the later simulator."""

    if predictions.ndim != 2 or predictions.shape[1] != len(targets):
        raise ValueError("statistics matrix does not match its target contract")
    if not np.isfinite(predictions).all() or np.any(predictions < 0.0):
        raise ValueError("statistics matrix contains invalid means")
    adjusted = predictions.copy()
    positions = {target.name: index for index, target in enumerate(targets)}
    for side in ("home", "away"):
        shots = positions[f"{side}_shots"]
        on_target = positions[f"{side}_shots_on_target"]
        adjusted[:, on_target] = np.minimum(adjusted[:, on_target], adjusted[:, shots])
    return adjusted


def _select_alpha(
    dataset: DetailedStatisticsDataset,
    target_index: int,
    grid: CountModelGrid,
) -> tuple[float, tuple[AlphaScore, ...]]:
    scores: list[AlphaScore] = []
    for alpha in grid.alpha_values:
        fold_scores: list[float] = []
        for train_seasons, validation_season in dataset.tabular.split.development_folds:
            train_indices = dataset.tabular.indices_for(train_seasons)
            validation_indices = dataset.tabular.indices_for((validation_season,))
            pipeline = build_count_pipeline(alpha)
            pipeline.fit(
                dataset.tabular.features[train_indices],
                dataset.targets[train_indices, target_index],
            )
            prediction = _predict(pipeline, dataset.tabular.features[validation_indices])
            fold_scores.append(
                float(
                    mean_poisson_deviance(
                        dataset.targets[validation_indices, target_index], prediction
                    )
                )
            )
        scores.append(
            AlphaScore(
                alpha=alpha,
                fold_deviances=tuple(fold_scores),
                mean_deviance=float(np.mean(fold_scores)),
            )
        )
    leaderboard = tuple(sorted(scores, key=lambda item: (item.mean_deviance, item.alpha)))
    return leaderboard[0].alpha, leaderboard


def _train_target(
    dataset: DetailedStatisticsDataset,
    target_index: int,
    grid: CountModelGrid,
) -> TargetTrainingResult:
    selected_alpha, leaderboard = _select_alpha(dataset, target_index, grid)
    split = dataset.tabular.split
    train_indices = dataset.tabular.indices_for(split.base_training_seasons)
    calibration_indices = dataset.tabular.indices_for((split.calibration_season,))
    holdout_indices = dataset.tabular.indices_for(split.holdout_seasons)
    pipeline = build_count_pipeline(selected_alpha)
    pipeline.fit(
        dataset.tabular.features[train_indices], dataset.targets[train_indices, target_index]
    )
    calibration_raw = _predict(pipeline, dataset.tabular.features[calibration_indices])
    calibration_actual = dataset.targets[calibration_indices, target_index]
    multiplier = float(
        np.clip(
            calibration_actual.sum() / max(float(calibration_raw.sum()), 1e-9),
            0.5,
            1.5,
        )
    )
    calibration_prediction = calibration_raw * multiplier
    residual_quantile = float(
        np.quantile(np.abs(calibration_actual - calibration_prediction), 0.90)
    )
    holdout_prediction = _predict(pipeline, dataset.tabular.features[holdout_indices]) * multiplier
    holdout_actual = dataset.targets[holdout_indices, target_index]
    prior_indices = dataset.tabular.indices_for(
        split.base_training_seasons + (split.calibration_season,)
    )
    baseline_mean = float(dataset.targets[prior_indices, target_index].mean())
    baseline_prediction = np.full(len(holdout_indices), baseline_mean, dtype=np.float64)
    model_metrics = _metrics(
        holdout_actual,
        holdout_prediction,
        residual_quantile_90=residual_quantile,
    )
    baseline_metrics = _metrics(
        holdout_actual,
        baseline_prediction,
        residual_quantile_90=residual_quantile,
    )
    use_model = (
        model_metrics.mean_absolute_error < baseline_metrics.mean_absolute_error
        and model_metrics.mean_poisson_deviance < baseline_metrics.mean_poisson_deviance
    )
    reason = (
        "Improved both holdout MAE and Poisson deviance over the historical-mean baseline."
        if use_model
        else "Did not improve both holdout MAE and Poisson deviance over the baseline."
    )
    return TargetTrainingResult(
        target=dataset.target_specs[target_index],
        selected_alpha=selected_alpha,
        leaderboard=leaderboard,
        calibration_multiplier=multiplier,
        residual_quantile_90=residual_quantile,
        holdout_metrics=model_metrics,
        baseline_metrics=baseline_metrics,
        use_model=use_model,
        reason=reason,
        baseline_mean=baseline_mean,
        fitted_pipeline=pipeline,
        holdout_predictions=holdout_prediction,
    )


def train_detailed_statistics_models(
    dataset: DetailedStatisticsDataset,
    *,
    grid: CountModelGrid | None = None,
) -> DetailedStatisticsTrainingResult:
    selected_grid = grid or CountModelGrid()
    targets = tuple(
        _train_target(dataset, target_index, selected_grid)
        for target_index in range(len(dataset.target_specs))
    )
    official_columns = [
        result.holdout_predictions
        if result.use_model
        else np.full(len(result.holdout_predictions), result.baseline_mean, dtype=np.float64)
        for result in targets
    ]
    official = reconcile_statistic_means(
        np.column_stack(official_columns), dataset.target_specs
    )
    return DetailedStatisticsTrainingResult(
        targets=targets,
        official_holdout_predictions=official,
        aggregate_model_mae=float(
            np.mean([result.holdout_metrics.mean_absolute_error for result in targets])
        ),
        aggregate_baseline_mae=float(
            np.mean([result.baseline_metrics.mean_absolute_error for result in targets])
        ),
        promoted_target_count=sum(result.use_model for result in targets),
    )
