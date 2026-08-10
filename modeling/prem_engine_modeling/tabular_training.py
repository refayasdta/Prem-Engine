"""Chronological selection, calibration, and evaluation for Phase 9."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize_scalar  # type: ignore[import-untyped]
from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.inspection import permutation_importance  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from prem_engine_modeling.elo import ResultProbabilities
from prem_engine_modeling.evaluation import EvaluationMetrics, MatchPrediction, evaluate_predictions
from prem_engine_modeling.tabular_data import CLASS_ORDER, TabularDataset

RANDOM_SEED = 42
ModelFamily = Literal["multinomial_logistic", "histogram_gradient_boosting"]


@dataclass(frozen=True, order=True)
class CandidateSpec:
    candidate_id: str
    family: ModelFamily
    regularization_c: float | None = None
    learning_rate: float | None = None
    max_leaf_nodes: int | None = None
    max_iterations: int | None = None
    l2_regularization: float | None = None


@dataclass(frozen=True)
class CandidateGrid:
    logistic_c_values: tuple[float, ...] = (0.03, 0.1, 0.3, 1.0)
    boosting_learning_rates: tuple[float, ...] = (0.03, 0.07)
    boosting_leaf_counts: tuple[int, ...] = (7, 15)
    boosting_l2_values: tuple[float, ...] = (0.1, 1.0)
    boosting_iterations: int = 160

    def candidates(self) -> tuple[CandidateSpec, ...]:
        logistic = tuple(
            CandidateSpec(
                candidate_id=f"logistic-c-{value:g}",
                family="multinomial_logistic",
                regularization_c=value,
            )
            for value in self.logistic_c_values
        )
        boosting = tuple(
            CandidateSpec(
                candidate_id=f"hgb-lr-{rate:g}-leaves-{leaves}-l2-{l2:g}",
                family="histogram_gradient_boosting",
                learning_rate=rate,
                max_leaf_nodes=leaves,
                max_iterations=self.boosting_iterations,
                l2_regularization=l2,
            )
            for rate in self.boosting_learning_rates
            for leaves in self.boosting_leaf_counts
            for l2 in self.boosting_l2_values
        )
        result = logistic + boosting
        if not result:
            raise ValueError("candidate grid cannot be empty")
        return result


@dataclass(frozen=True)
class FoldScore:
    train_seasons: tuple[str, ...]
    validation_season: str
    metrics: EvaluationMetrics


@dataclass(frozen=True)
class CandidateScore:
    spec: CandidateSpec
    fold_scores: tuple[FoldScore, ...]
    mean_log_loss: float
    mean_brier_score: float


@dataclass(frozen=True)
class FeatureInfluence:
    feature: str
    importance: float
    home_effect: float | None
    draw_effect: float | None
    away_effect: float | None


@dataclass(frozen=True)
class PromotionVerdict:
    status: Literal["promoted", "ensemble_candidate", "rejected"]
    reason: str
    best_benchmark: str
    log_loss_improvement: float


@dataclass(frozen=True)
class TabularTrainingResult:
    selected_candidate: CandidateSpec
    leaderboard: tuple[CandidateScore, ...]
    calibration_temperature: float
    calibration_uncalibrated_metrics: EvaluationMetrics
    calibration_calibrated_metrics: EvaluationMetrics
    holdout_uncalibrated_metrics: EvaluationMetrics
    holdout_calibrated_metrics: EvaluationMetrics
    holdout_metrics_by_season: dict[str, EvaluationMetrics]
    elo_holdout_metrics: EvaluationMetrics
    goal_holdout_metrics: EvaluationMetrics
    historical_prior_holdout_metrics: EvaluationMetrics
    feature_influences: tuple[FeatureInfluence, ...]
    promotion: PromotionVerdict
    fitted_pipeline: Any
    holdout_probabilities: NDArray[np.float64]


def build_candidate_pipeline(spec: CandidateSpec) -> Any:
    if spec.family == "multinomial_logistic":
        if spec.regularization_c is None:
            raise ValueError("logistic candidate needs regularization C")
        return Pipeline(
            steps=(
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("scaler", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        C=spec.regularization_c,
                        solver="lbfgs",
                        max_iter=2000,
                        random_state=RANDOM_SEED,
                    ),
                ),
            )
        )
    required = (
        spec.learning_rate,
        spec.max_leaf_nodes,
        spec.max_iterations,
        spec.l2_regularization,
    )
    if any(value is None for value in required):
        raise ValueError("boosting candidate is incomplete")
    return Pipeline(
        steps=(
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            (
                "model",
                HistGradientBoostingClassifier(
                    learning_rate=spec.learning_rate,
                    max_leaf_nodes=spec.max_leaf_nodes,
                    max_iter=spec.max_iterations,
                    l2_regularization=spec.l2_regularization,
                    early_stopping=False,
                    random_state=RANDOM_SEED,
                ),
            ),
        )
    )


def _ordered_probabilities(pipeline: Any, features: NDArray[np.float64]) -> NDArray[np.float64]:
    probabilities = np.asarray(pipeline.predict_proba(features), dtype=np.float64)
    classes = tuple(int(value) for value in pipeline.classes_)
    if set(classes) != {0, 1, 2}:
        raise ValueError("classifier did not preserve all three result classes")
    ordered = probabilities[:, [classes.index(index) for index in range(3)]]
    if not np.isfinite(ordered).all() or np.any(ordered < 0.0):
        raise ValueError("classifier emitted invalid probabilities")
    totals = ordered.sum(axis=1)
    if not np.allclose(totals, 1.0, atol=1e-10):
        raise ValueError("classifier probabilities do not sum to one")
    return ordered


def _predictions(
    dataset: TabularDataset,
    *,
    seasons: tuple[str, ...],
    probabilities: NDArray[np.float64],
) -> tuple[MatchPrediction, ...]:
    indices = dataset.indices_for(seasons)
    if len(indices) != len(probabilities):
        raise ValueError("probability count does not match requested seasons")
    result: list[MatchPrediction] = []
    for row_index, values in zip(indices, probabilities, strict=True):
        target = CLASS_ORDER[int(dataset.targets[row_index])]
        result.append(
            MatchPrediction(
                match_uuid=dataset.match_uuids[row_index],
                season=dataset.seasons_by_row[row_index],
                kickoff_at=dataset.kickoffs[row_index],
                actual_result=target,
                probabilities=ResultProbabilities(
                    home=float(values[0]),
                    draw=float(values[1]),
                    away=float(values[2]),
                ),
            )
        )
    return tuple(result)


def _metrics(
    dataset: TabularDataset,
    *,
    seasons: tuple[str, ...],
    probabilities: NDArray[np.float64],
) -> EvaluationMetrics:
    return evaluate_predictions(_predictions(dataset, seasons=seasons, probabilities=probabilities))


def evaluate_candidate(dataset: TabularDataset, spec: CandidateSpec) -> CandidateScore:
    folds: list[FoldScore] = []
    for train_seasons, validation_season in dataset.split.development_folds:
        train_features, train_targets = dataset.matrix_for(train_seasons)
        validation_features, _ = dataset.matrix_for((validation_season,))
        pipeline = build_candidate_pipeline(spec)
        pipeline.fit(train_features, train_targets)
        probabilities = _ordered_probabilities(pipeline, validation_features)
        metrics = _metrics(
            dataset,
            seasons=(validation_season,),
            probabilities=probabilities,
        )
        folds.append(FoldScore(train_seasons, validation_season, metrics))
    return CandidateScore(
        spec=spec,
        fold_scores=tuple(folds),
        mean_log_loss=sum(fold.metrics.log_loss for fold in folds) / len(folds),
        mean_brier_score=sum(fold.metrics.brier_score for fold in folds) / len(folds),
    )


def temperature_scale_probabilities(
    probabilities: NDArray[np.float64], temperature: float
) -> NDArray[np.float64]:
    if not math.isfinite(temperature) or temperature <= 0.0:
        raise ValueError("temperature must be finite and positive")
    logits = np.log(np.clip(probabilities, 1e-15, 1.0)) / temperature
    logits -= logits.max(axis=1, keepdims=True)
    exponentials = np.exp(logits)
    return np.asarray(exponentials / exponentials.sum(axis=1, keepdims=True), dtype=np.float64)


def fit_temperature(probabilities: NDArray[np.float64], targets: NDArray[np.int64]) -> float:
    def objective(log_temperature: float) -> float:
        calibrated = temperature_scale_probabilities(probabilities, math.exp(log_temperature))
        true_probabilities = calibrated[np.arange(len(targets)), targets]
        return float(-np.log(np.clip(true_probabilities, 1e-15, 1.0)).mean())

    optimized = minimize_scalar(objective, bounds=(math.log(0.25), math.log(4.0)), method="bounded")
    if not optimized.success:
        raise RuntimeError("temperature calibration failed")
    return float(math.exp(optimized.x))


def _benchmark_probabilities(
    dataset: TabularDataset, columns: tuple[str, str, str], seasons: tuple[str, ...]
) -> NDArray[np.float64]:
    positions = [dataset.feature_columns.index(column) for column in columns]
    indices = dataset.indices_for(seasons)
    return np.asarray(dataset.features[indices][:, positions], dtype=np.float64)


def _historical_prior_probabilities(dataset: TabularDataset) -> NDArray[np.float64]:
    train_indices = dataset.indices_for(
        dataset.split.base_training_seasons + (dataset.split.calibration_season,)
    )
    counts = np.bincount(dataset.targets[train_indices], minlength=3).astype(np.float64) + 1.0
    probabilities = counts / counts.sum()
    holdout_count = len(dataset.indices_for(dataset.split.holdout_seasons))
    return np.tile(probabilities, (holdout_count, 1))


def _feature_influences(
    pipeline: Any,
    spec: CandidateSpec,
    dataset: TabularDataset,
) -> tuple[FeatureInfluence, ...]:
    if spec.family == "multinomial_logistic":
        coefficients = np.asarray(pipeline.named_steps["model"].coef_, dtype=np.float64)
        influences = [
            FeatureInfluence(
                feature=feature,
                importance=float(np.linalg.norm(coefficients[:, index])),
                home_effect=float(coefficients[0, index]),
                draw_effect=float(coefficients[1, index]),
                away_effect=float(coefficients[2, index]),
            )
            for index, feature in enumerate(dataset.feature_columns)
        ]
    else:
        calibration_features, calibration_targets = dataset.matrix_for(
            (dataset.split.calibration_season,)
        )
        measured = permutation_importance(
            pipeline,
            calibration_features,
            calibration_targets,
            scoring="neg_log_loss",
            n_repeats=3,
            random_state=RANDOM_SEED,
            n_jobs=1,
        )
        influences = [
            FeatureInfluence(
                feature=feature,
                importance=float(max(0.0, measured.importances_mean[index])),
                home_effect=None,
                draw_effect=None,
                away_effect=None,
            )
            for index, feature in enumerate(dataset.feature_columns)
        ]
    return tuple(sorted(influences, key=lambda item: (-item.importance, item.feature))[:12])


def _promotion_verdict(
    tabular: EvaluationMetrics,
    elo: EvaluationMetrics,
    goals: EvaluationMetrics,
) -> PromotionVerdict:
    benchmarks = {"Phase 6 Elo": elo, "Phase 7 goals": goals}
    best_name, best = min(benchmarks.items(), key=lambda item: item[1].log_loss)
    improvement = best.log_loss - tabular.log_loss
    if improvement >= 0.005 and tabular.brier_score < best.brier_score:
        return PromotionVerdict(
            status="promoted",
            reason="Improved holdout log loss by at least 0.005 and also improved Brier score.",
            best_benchmark=best_name,
            log_loss_improvement=improvement,
        )
    if improvement > 0.0:
        return PromotionVerdict(
            status="ensemble_candidate",
            reason=(
                "Improved log loss, but not by the full promotion margin on both primary metrics."
            ),
            best_benchmark=best_name,
            log_loss_improvement=improvement,
        )
    return PromotionVerdict(
        status="rejected",
        reason="Did not improve holdout log loss over the best established benchmark.",
        best_benchmark=best_name,
        log_loss_improvement=improvement,
    )


def train_tabular_model(
    dataset: TabularDataset,
    *,
    candidate_grid: CandidateGrid | None = None,
) -> TabularTrainingResult:
    candidates = (candidate_grid or CandidateGrid()).candidates()
    leaderboard = tuple(
        sorted(
            (evaluate_candidate(dataset, spec) for spec in candidates),
            key=lambda item: (item.mean_log_loss, item.mean_brier_score, item.spec.candidate_id),
        )
    )
    selected = leaderboard[0].spec
    base_features, base_targets = dataset.matrix_for(dataset.split.base_training_seasons)
    calibration_features, calibration_targets = dataset.matrix_for(
        (dataset.split.calibration_season,)
    )
    holdout_features, _ = dataset.matrix_for(dataset.split.holdout_seasons)
    pipeline = build_candidate_pipeline(selected)
    pipeline.fit(base_features, base_targets)

    calibration_raw = _ordered_probabilities(pipeline, calibration_features)
    temperature = fit_temperature(calibration_raw, calibration_targets)
    calibration_adjusted = temperature_scale_probabilities(calibration_raw, temperature)
    holdout_raw = _ordered_probabilities(pipeline, holdout_features)
    holdout_adjusted = temperature_scale_probabilities(holdout_raw, temperature)

    elo_probabilities = _benchmark_probabilities(
        dataset,
        ("elo_home_probability", "elo_draw_probability", "elo_away_probability"),
        dataset.split.holdout_seasons,
    )
    goal_probabilities = _benchmark_probabilities(
        dataset,
        ("goal_home_probability", "goal_draw_probability", "goal_away_probability"),
        dataset.split.holdout_seasons,
    )
    calibrated_metrics = _metrics(
        dataset,
        seasons=dataset.split.holdout_seasons,
        probabilities=holdout_adjusted,
    )
    elo_metrics = _metrics(
        dataset, seasons=dataset.split.holdout_seasons, probabilities=elo_probabilities
    )
    goal_metrics = _metrics(
        dataset, seasons=dataset.split.holdout_seasons, probabilities=goal_probabilities
    )
    by_season = {
        season: _metrics(
            dataset,
            seasons=(season,),
            probabilities=holdout_adjusted[
                np.asarray(
                    [
                        value == season
                        for value in np.asarray(dataset.seasons_by_row)[
                            dataset.indices_for(dataset.split.holdout_seasons)
                        ]
                    ],
                    dtype=bool,
                )
            ],
        )
        for season in dataset.split.holdout_seasons
    }
    return TabularTrainingResult(
        selected_candidate=selected,
        leaderboard=leaderboard,
        calibration_temperature=temperature,
        calibration_uncalibrated_metrics=_metrics(
            dataset,
            seasons=(dataset.split.calibration_season,),
            probabilities=calibration_raw,
        ),
        calibration_calibrated_metrics=_metrics(
            dataset,
            seasons=(dataset.split.calibration_season,),
            probabilities=calibration_adjusted,
        ),
        holdout_uncalibrated_metrics=_metrics(
            dataset,
            seasons=dataset.split.holdout_seasons,
            probabilities=holdout_raw,
        ),
        holdout_calibrated_metrics=calibrated_metrics,
        holdout_metrics_by_season=by_season,
        elo_holdout_metrics=elo_metrics,
        goal_holdout_metrics=goal_metrics,
        historical_prior_holdout_metrics=_metrics(
            dataset,
            seasons=dataset.split.holdout_seasons,
            probabilities=_historical_prior_probabilities(dataset),
        ),
        feature_influences=_feature_influences(pipeline, selected, dataset),
        promotion=_promotion_verdict(calibrated_metrics, elo_metrics, goal_metrics),
        fitted_pipeline=pipeline,
        holdout_probabilities=holdout_adjusted,
    )


def calibrated_predict_proba(
    pipeline: Any,
    features: NDArray[np.float64],
    *,
    temperature: float,
) -> NDArray[np.float64]:
    return temperature_scale_probabilities(_ordered_probabilities(pipeline, features), temperature)
