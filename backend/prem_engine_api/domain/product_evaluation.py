"""Runtime evaluation of locked forecasts against accepted real results."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

Outcome = Literal["home", "draw", "away"]
EVALUATION_CALCULATION_VERSION = "official-forecast-evaluation-v1"


@dataclass(frozen=True)
class ForecastEvaluationInput:
    match_uuid: UUID
    home_probability: float
    draw_probability: float
    away_probability: float
    expected_home_goals: float
    expected_away_goals: float
    simulated_home_goals: int
    simulated_away_goals: int
    actual_home_goals: int
    actual_away_goals: int
    excluded_from_aggregate: bool = False


@dataclass(frozen=True)
class EvaluatedForecast:
    match_uuid: UUID
    actual_outcome: Outcome
    forecast_outcome: Outcome
    simulation_outcome: Outcome
    forecast_outcome_correct: bool
    simulation_outcome_correct: bool
    exact_simulated_score_correct: bool
    log_loss: float
    brier_score: float
    ranked_probability_score: float
    expected_goal_mae: float
    excluded_from_aggregate: bool


@dataclass(frozen=True)
class AggregateEvaluation:
    sample_count: int
    excluded_count: int
    outcome_accuracy: float | None
    simulation_outcome_accuracy: float | None
    exact_simulated_score_accuracy: float | None
    log_loss: float | None
    brier_score: float | None
    ranked_probability_score: float | None
    expected_goal_mae: float | None
    expected_calibration_error: float | None


def outcome(home_goals: int, away_goals: int) -> Outcome:
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def evaluate_forecast(item: ForecastEvaluationInput) -> EvaluatedForecast:
    probabilities = (item.home_probability, item.draw_probability, item.away_probability)
    outcomes: tuple[Outcome, Outcome, Outcome] = ("home", "draw", "away")
    actual = outcome(item.actual_home_goals, item.actual_away_goals)
    forecast = outcomes[max(range(3), key=probabilities.__getitem__)]
    simulated = outcome(item.simulated_home_goals, item.simulated_away_goals)
    actual_index = outcomes.index(actual)
    observed = tuple(1.0 if index == actual_index else 0.0 for index in range(3))
    brier = sum(
        (probability - target) ** 2
        for probability, target in zip(probabilities, observed, strict=True)
    )
    home_cumulative = probabilities[0] - observed[0]
    draw_cumulative = probabilities[0] + probabilities[1] - observed[0] - observed[1]
    ranked = (home_cumulative**2 + draw_cumulative**2) / 2
    return EvaluatedForecast(
        match_uuid=item.match_uuid,
        actual_outcome=actual,
        forecast_outcome=forecast,
        simulation_outcome=simulated,
        forecast_outcome_correct=forecast == actual,
        simulation_outcome_correct=simulated == actual,
        exact_simulated_score_correct=(
            item.simulated_home_goals == item.actual_home_goals
            and item.simulated_away_goals == item.actual_away_goals
        ),
        log_loss=-math.log(max(1e-15, min(1.0 - 1e-15, probabilities[actual_index]))),
        brier_score=brier,
        ranked_probability_score=ranked,
        expected_goal_mae=(
            abs(item.expected_home_goals - item.actual_home_goals)
            + abs(item.expected_away_goals - item.actual_away_goals)
        )
        / 2,
        excluded_from_aggregate=item.excluded_from_aggregate,
    )


def aggregate_evaluations(
    inputs: tuple[ForecastEvaluationInput, ...], *, calibration_bin_count: int = 10
) -> tuple[AggregateEvaluation, tuple[EvaluatedForecast, ...]]:
    if calibration_bin_count <= 0:
        raise ValueError("calibration bin count must be positive")
    evaluated = tuple(evaluate_forecast(item) for item in inputs)
    included_pairs = tuple(
        (item, result)
        for item, result in zip(inputs, evaluated, strict=True)
        if not result.excluded_from_aggregate
    )
    if not included_pairs:
        return (
            AggregateEvaluation(
                sample_count=0,
                excluded_count=len(evaluated),
                outcome_accuracy=None,
                simulation_outcome_accuracy=None,
                exact_simulated_score_accuracy=None,
                log_loss=None,
                brier_score=None,
                ranked_probability_score=None,
                expected_goal_mae=None,
                expected_calibration_error=None,
            ),
            evaluated,
        )

    buckets: list[list[tuple[float, float]]] = [[] for _ in range(calibration_bin_count)]
    outcomes: tuple[Outcome, Outcome, Outcome] = ("home", "draw", "away")
    for item, result in included_pairs:
        probabilities = (item.home_probability, item.draw_probability, item.away_probability)
        actual_index = outcomes.index(result.actual_outcome)
        for index, probability in enumerate(probabilities):
            bucket = min(int(probability * calibration_bin_count), calibration_bin_count - 1)
            buckets[bucket].append((probability, 1.0 if index == actual_index else 0.0))
    observation_count = len(included_pairs) * 3
    calibration_error = sum(
        (len(bucket) / observation_count)
        * abs(
            sum(probability for probability, _ in bucket) / len(bucket)
            - sum(observed for _, observed in bucket) / len(bucket)
        )
        for bucket in buckets
        if bucket
    )
    results = tuple(result for _, result in included_pairs)
    count = len(results)
    return (
        AggregateEvaluation(
            sample_count=count,
            excluded_count=len(evaluated) - count,
            outcome_accuracy=sum(result.forecast_outcome_correct for result in results) / count,
            simulation_outcome_accuracy=(
                sum(result.simulation_outcome_correct for result in results) / count
            ),
            exact_simulated_score_accuracy=(
                sum(result.exact_simulated_score_correct for result in results) / count
            ),
            log_loss=sum(result.log_loss for result in results) / count,
            brier_score=sum(result.brier_score for result in results) / count,
            ranked_probability_score=(
                sum(result.ranked_probability_score for result in results) / count
            ),
            expected_goal_mae=sum(result.expected_goal_mae for result in results) / count,
            expected_calibration_error=calibration_error,
        ),
        evaluated,
    )
