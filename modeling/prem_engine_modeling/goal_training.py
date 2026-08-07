"""Leakage-safe walk-forward training for the Phase 7 goal model."""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass
from datetime import datetime

from prem_engine_modeling.data import (
    ChronologicalSplit,
    HistoricalDataset,
    MatchRecord,
    standard_six_season_split,
)
from prem_engine_modeling.evaluation import EvaluationMetrics
from prem_engine_modeling.goal_evaluation import (
    GoalEvaluationMetrics,
    GoalPrediction,
    evaluate_goal_predictions,
    fixed_goal_predictions,
)
from prem_engine_modeling.goals import DynamicGoalModel, GoalModelConfig, forecast_from_rates
from prem_engine_modeling.training import BaselineTrainingResult, train_baseline


@dataclass(frozen=True)
class GoalParameterGrid:
    learning_rates: tuple[float, ...] = (0.015, 0.03, 0.06)
    base_goal_rates: tuple[float, ...] = (1.25, 1.35, 1.45)
    home_advantages: tuple[float, ...] = (0.10, 0.18, 0.26)
    dixon_coles_rhos: tuple[float, ...] = (-0.12, -0.06, 0.0)
    season_carryovers: tuple[float, ...] = (0.80, 0.95)

    def configurations(self) -> tuple[GoalModelConfig, ...]:
        return tuple(
            GoalModelConfig(
                learning_rate=learning_rate,
                base_goal_rate=base_goal_rate,
                home_advantage=home_advantage,
                dixon_coles_rho=dixon_coles_rho,
                season_carryover=season_carryover,
            )
            for (
                learning_rate,
                base_goal_rate,
                home_advantage,
                dixon_coles_rho,
                season_carryover,
            ) in itertools.product(
                self.learning_rates,
                self.base_goal_rates,
                self.home_advantages,
                self.dixon_coles_rhos,
                self.season_carryovers,
            )
        )


@dataclass(frozen=True)
class GoalWalkForwardResult:
    predictions: tuple[GoalPrediction, ...]
    final_attack: dict[str, float]
    final_defence: dict[str, float]


@dataclass(frozen=True)
class GoalTuningResult:
    selected_config: GoalModelConfig
    validation_metrics: GoalEvaluationMetrics
    candidate_count: int


@dataclass(frozen=True)
class GoalTrainingResult:
    split: ChronologicalSplit
    tuning: GoalTuningResult
    holdout_metrics: GoalEvaluationMetrics
    holdout_metrics_by_season: dict[str, GoalEvaluationMetrics]
    league_average_home_goals: float
    league_average_away_goals: float
    league_average_metrics: GoalEvaluationMetrics
    elo_holdout_metrics: EvaluationMetrics
    test_predictions: tuple[GoalPrediction, ...]
    final_attack: dict[str, float]
    final_defence: dict[str, float]


def walk_forward_goals(
    dataset: HistoricalDataset,
    *,
    config: GoalModelConfig,
    score_seasons: tuple[str, ...],
) -> GoalWalkForwardResult:
    unknown = set(score_seasons).difference(dataset.seasons)
    if unknown:
        raise ValueError(f"score seasons are absent from the dataset: {sorted(unknown)}")
    model = DynamicGoalModel(config)
    pending: list[tuple[datetime, str, MatchRecord]] = []
    predictions: list[GoalPrediction] = []
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
        forecast = model.predict(match.home_club_uuid, match.away_club_uuid)
        if match.season in score_seasons:
            predictions.append(
                GoalPrediction(
                    match_uuid=match.match_uuid,
                    season=match.season,
                    kickoff_at=match.kickoff_at.isoformat(),
                    actual_home_goals=match.home_goals,
                    actual_away_goals=match.away_goals,
                    actual_result=match.result,
                    forecast=forecast,
                )
            )
        heapq.heappush(pending, (match.available_after, match.match_uuid, match))
    apply_available()
    return GoalWalkForwardResult(
        predictions=tuple(predictions),
        final_attack=model.attack_snapshot(),
        final_defence=model.defence_snapshot(),
    )


def tune_goal_model(
    dataset: HistoricalDataset,
    *,
    split: ChronologicalSplit,
    parameter_grid: GoalParameterGrid,
) -> GoalTuningResult:
    validation_data = dataset.through_season(split.validation_season)
    candidates = parameter_grid.configurations()
    if not candidates:
        raise ValueError("goal parameter grid cannot be empty")
    scored: list[tuple[float, float, GoalModelConfig, GoalEvaluationMetrics]] = []
    for config in candidates:
        output = walk_forward_goals(
            validation_data,
            config=config,
            score_seasons=(split.validation_season,),
        )
        metrics = evaluate_goal_predictions(output.predictions)
        scored.append(
            (
                metrics.scoreline_log_loss,
                metrics.outcome_metrics.log_loss,
                config,
                metrics,
            )
        )
    _, _, selected, validation_metrics = min(scored, key=lambda item: item[:3])
    return GoalTuningResult(
        selected_config=selected,
        validation_metrics=validation_metrics,
        candidate_count=len(candidates),
    )


def _league_average_baseline(
    dataset: HistoricalDataset, split: ChronologicalSplit
) -> tuple[float, float, GoalEvaluationMetrics]:
    first_test_kickoff = min(
        record.kickoff_at for record in dataset.records if record.season in split.test_seasons
    )
    prior = tuple(
        record for record in dataset.records if record.available_after < first_test_kickoff
    )
    test = tuple(record for record in dataset.records if record.season in split.test_seasons)
    home_rate = sum(record.home_goals for record in prior) / len(prior)
    away_rate = sum(record.away_goals for record in prior) / len(prior)
    forecast = forecast_from_rates(home_rate, away_rate)
    metrics = evaluate_goal_predictions(fixed_goal_predictions(test, forecast))
    return home_rate, away_rate, metrics


def train_goal_model(
    dataset: HistoricalDataset,
    *,
    parameter_grid: GoalParameterGrid | None = None,
    elo_result: BaselineTrainingResult | None = None,
) -> GoalTrainingResult:
    split = standard_six_season_split(dataset)
    tuning = tune_goal_model(
        dataset,
        split=split,
        parameter_grid=parameter_grid or GoalParameterGrid(),
    )
    output = walk_forward_goals(
        dataset,
        config=tuning.selected_config,
        score_seasons=split.test_seasons,
    )
    holdout = evaluate_goal_predictions(output.predictions)
    by_season = {
        season: evaluate_goal_predictions(
            tuple(prediction for prediction in output.predictions if prediction.season == season)
        )
        for season in split.test_seasons
    }
    home_rate, away_rate, league_metrics = _league_average_baseline(dataset, split)
    phase_six = elo_result or train_baseline(dataset)
    return GoalTrainingResult(
        split=split,
        tuning=tuning,
        holdout_metrics=holdout,
        holdout_metrics_by_season=by_season,
        league_average_home_goals=home_rate,
        league_average_away_goals=away_rate,
        league_average_metrics=league_metrics,
        elo_holdout_metrics=phase_six.elo_test_metrics,
        test_predictions=output.predictions,
        final_attack=output.final_attack,
        final_defence=output.final_defence,
    )
