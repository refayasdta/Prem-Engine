"""Chronological tuning and holdout evaluation for the Elo baseline."""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass
from datetime import datetime

from prem_engine_modeling.data import (
    RESULT_ORDER,
    ChronologicalSplit,
    HistoricalDataset,
    MatchRecord,
    standard_six_season_split,
)
from prem_engine_modeling.elo import EloConfig, EloModel, ResultProbabilities
from prem_engine_modeling.evaluation import (
    EvaluationMetrics,
    MatchPrediction,
    evaluate_predictions,
    fixed_probability_predictions,
)


@dataclass(frozen=True)
class ParameterGrid:
    k_factors: tuple[float, ...] = (12.0, 20.0, 28.0, 36.0)
    home_advantages: tuple[float, ...] = (40.0, 60.0, 80.0, 100.0)
    draw_propensities: tuple[float, ...] = (0.50, 0.65, 0.80)
    margin_weights: tuple[float, ...] = (0.0, 0.25, 0.50)
    season_carryovers: tuple[float, ...] = (0.75, 0.85, 0.95)

    def configurations(self) -> tuple[EloConfig, ...]:
        values = itertools.product(
            self.k_factors,
            self.home_advantages,
            self.draw_propensities,
            self.margin_weights,
            self.season_carryovers,
        )
        return tuple(
            EloConfig(
                k_factor=k_factor,
                home_advantage=home_advantage,
                draw_propensity=draw_propensity,
                margin_weight=margin_weight,
                season_carryover=season_carryover,
            )
            for k_factor, home_advantage, draw_propensity, margin_weight, season_carryover in values
        )


@dataclass(frozen=True)
class WalkForwardResult:
    predictions: tuple[MatchPrediction, ...]
    final_ratings: dict[str, float]


@dataclass(frozen=True)
class TuningResult:
    selected_config: EloConfig
    validation_metrics: EvaluationMetrics
    candidate_count: int


@dataclass(frozen=True)
class BaselineTrainingResult:
    split: ChronologicalSplit
    tuning: TuningResult
    elo_test_metrics: EvaluationMetrics
    elo_test_metrics_by_season: dict[str, EvaluationMetrics]
    empirical_baseline_probabilities: ResultProbabilities
    empirical_baseline_metrics: EvaluationMetrics
    uniform_baseline_metrics: EvaluationMetrics
    test_predictions: tuple[MatchPrediction, ...]
    final_ratings: dict[str, float]


def walk_forward(
    dataset: HistoricalDataset,
    *,
    config: EloConfig,
    score_seasons: tuple[str, ...],
) -> WalkForwardResult:
    """Predict first, then update only when a completed record becomes available."""

    unknown = set(score_seasons).difference(dataset.seasons)
    if unknown:
        raise ValueError(f"score seasons are absent from the dataset: {sorted(unknown)}")
    model = EloModel(config)
    pending: list[tuple[datetime, str, MatchRecord]] = []
    predictions: list[MatchPrediction] = []
    current_season: str | None = None

    def apply_available(cutoff: datetime | None = None) -> None:
        while pending and (cutoff is None or pending[0][0] < cutoff):
            _, _, completed = heapq.heappop(pending)
            model.update(completed)

    for match in dataset.records:
        apply_available(match.kickoff_at)
        if match.season != current_season:
            model.begin_season(match.season)
            current_season = match.season
        probabilities = model.predict(match.home_club_uuid, match.away_club_uuid)
        if match.season in score_seasons:
            predictions.append(
                MatchPrediction(
                    match_uuid=match.match_uuid,
                    season=match.season,
                    kickoff_at=match.kickoff_at.isoformat(),
                    actual_result=match.result,
                    probabilities=probabilities,
                )
            )
        heapq.heappush(pending, (match.available_after, match.match_uuid, match))
    apply_available()
    return WalkForwardResult(
        predictions=tuple(predictions),
        final_ratings=model.ratings_snapshot(),
    )


def tune_elo(
    dataset: HistoricalDataset,
    *,
    split: ChronologicalSplit,
    parameter_grid: ParameterGrid,
) -> TuningResult:
    """Choose parameters on validation log loss without reading test seasons."""

    validation_data = dataset.through_season(split.validation_season)
    candidates = parameter_grid.configurations()
    if not candidates:
        raise ValueError("parameter grid cannot be empty")
    scored: list[tuple[float, float, EloConfig, EvaluationMetrics]] = []
    for config in candidates:
        output = walk_forward(
            validation_data,
            config=config,
            score_seasons=(split.validation_season,),
        )
        metrics = evaluate_predictions(output.predictions)
        scored.append((metrics.log_loss, metrics.brier_score, config, metrics))
    _, _, selected_config, validation_metrics = min(scored, key=lambda item: item[:3])
    return TuningResult(
        selected_config=selected_config,
        validation_metrics=validation_metrics,
        candidate_count=len(candidates),
    )


def _empirical_probabilities(records: tuple[MatchRecord, ...]) -> ResultProbabilities:
    counts = {result: 1 for result in RESULT_ORDER}
    for record in records:
        counts[record.result] += 1
    total = sum(counts.values())
    return ResultProbabilities(
        home=counts["H"] / total,
        draw=counts["D"] / total,
        away=counts["A"] / total,
    )


def train_baseline(
    dataset: HistoricalDataset, *, parameter_grid: ParameterGrid | None = None
) -> BaselineTrainingResult:
    """Tune on 2023/24 and report final metrics on two untouched holdout seasons."""

    split = standard_six_season_split(dataset)
    tuning = tune_elo(
        dataset,
        split=split,
        parameter_grid=parameter_grid or ParameterGrid(),
    )
    elo_output = walk_forward(
        dataset,
        config=tuning.selected_config,
        score_seasons=split.test_seasons,
    )
    elo_metrics = evaluate_predictions(elo_output.predictions)
    by_season = {
        season: evaluate_predictions(
            tuple(
                prediction for prediction in elo_output.predictions if prediction.season == season
            )
        )
        for season in split.test_seasons
    }

    first_test_kickoff = min(
        record.kickoff_at for record in dataset.records if record.season in split.test_seasons
    )
    prior_records = tuple(
        record for record in dataset.records if record.available_after < first_test_kickoff
    )
    test_records = tuple(
        record for record in dataset.records if record.season in split.test_seasons
    )
    empirical = _empirical_probabilities(prior_records)
    empirical_metrics = evaluate_predictions(fixed_probability_predictions(test_records, empirical))
    uniform = ResultProbabilities(home=1 / 3, draw=1 / 3, away=1 / 3)
    uniform_metrics = evaluate_predictions(fixed_probability_predictions(test_records, uniform))
    return BaselineTrainingResult(
        split=split,
        tuning=tuning,
        elo_test_metrics=elo_metrics,
        elo_test_metrics_by_season=by_season,
        empirical_baseline_probabilities=empirical,
        empirical_baseline_metrics=empirical_metrics,
        uniform_baseline_metrics=uniform_metrics,
        test_predictions=elo_output.predictions,
        final_ratings=elo_output.final_ratings,
    )
