"""Goal and scoreline evaluation for Phase 7 models."""

from __future__ import annotations

import math
from dataclasses import dataclass

from prem_engine_modeling.data import MatchRecord, MatchResult
from prem_engine_modeling.evaluation import EvaluationMetrics, MatchPrediction, evaluate_predictions
from prem_engine_modeling.goals import GoalForecast


@dataclass(frozen=True)
class GoalPrediction:
    match_uuid: str
    season: str
    kickoff_at: str
    actual_home_goals: int
    actual_away_goals: int
    actual_result: MatchResult
    forecast: GoalForecast


@dataclass(frozen=True)
class GoalEvaluationMetrics:
    sample_count: int
    mean_actual_home_goals: float
    mean_actual_away_goals: float
    mean_predicted_home_goals: float
    mean_predicted_away_goals: float
    home_goal_mae: float
    away_goal_mae: float
    mean_goal_mae: float
    goal_rmse: float
    exact_score_accuracy: float
    scoreline_log_loss: float
    outcome_metrics: EvaluationMetrics


def evaluate_goal_predictions(
    predictions: tuple[GoalPrediction, ...],
) -> GoalEvaluationMetrics:
    if not predictions:
        raise ValueError("at least one goal prediction is required")
    home_absolute = 0.0
    away_absolute = 0.0
    squared = 0.0
    exact = 0
    scoreline_loss = 0.0
    actual_home_total = 0
    actual_away_total = 0
    predicted_home_total = 0.0
    predicted_away_total = 0.0
    outcome_predictions: list[MatchPrediction] = []
    epsilon = 1e-15
    for prediction in predictions:
        forecast = prediction.forecast
        home_difference = forecast.expected_home_goals - prediction.actual_home_goals
        away_difference = forecast.expected_away_goals - prediction.actual_away_goals
        home_absolute += abs(home_difference)
        away_absolute += abs(away_difference)
        squared += home_difference**2 + away_difference**2
        actual_home_total += prediction.actual_home_goals
        actual_away_total += prediction.actual_away_goals
        predicted_home_total += forecast.expected_home_goals
        predicted_away_total += forecast.expected_away_goals
        best = forecast.top_scorelines(1)[0]
        exact += int(
            best.home_goals == prediction.actual_home_goals
            and best.away_goals == prediction.actual_away_goals
        )
        actual_probability = forecast.probability(
            prediction.actual_home_goals, prediction.actual_away_goals
        )
        scoreline_loss -= math.log(max(epsilon, actual_probability))
        outcome_predictions.append(
            MatchPrediction(
                match_uuid=prediction.match_uuid,
                season=prediction.season,
                kickoff_at=prediction.kickoff_at,
                actual_result=prediction.actual_result,
                probabilities=forecast.outcome_probabilities,
            )
        )
    count = len(predictions)
    return GoalEvaluationMetrics(
        sample_count=count,
        mean_actual_home_goals=actual_home_total / count,
        mean_actual_away_goals=actual_away_total / count,
        mean_predicted_home_goals=predicted_home_total / count,
        mean_predicted_away_goals=predicted_away_total / count,
        home_goal_mae=home_absolute / count,
        away_goal_mae=away_absolute / count,
        mean_goal_mae=(home_absolute + away_absolute) / (count * 2),
        goal_rmse=math.sqrt(squared / (count * 2)),
        exact_score_accuracy=exact / count,
        scoreline_log_loss=scoreline_loss / count,
        outcome_metrics=evaluate_predictions(tuple(outcome_predictions)),
    )


def fixed_goal_predictions(
    records: tuple[MatchRecord, ...], forecast: GoalForecast
) -> tuple[GoalPrediction, ...]:
    return tuple(
        GoalPrediction(
            match_uuid=record.match_uuid,
            season=record.season,
            kickoff_at=record.kickoff_at.isoformat(),
            actual_home_goals=record.home_goals,
            actual_away_goals=record.away_goals,
            actual_result=record.result,
            forecast=forecast,
        )
        for record in records
    )
