"""Probability-quality metrics and calibration summaries."""

from __future__ import annotations

import math
from dataclasses import dataclass

from prem_engine_modeling.data import RESULT_ORDER, MatchRecord, MatchResult
from prem_engine_modeling.elo import ResultProbabilities


@dataclass(frozen=True)
class MatchPrediction:
    match_uuid: str
    season: str
    kickoff_at: str
    actual_result: MatchResult
    probabilities: ResultProbabilities


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_probability: float | None
    observed_frequency: float | None


@dataclass(frozen=True)
class EvaluationMetrics:
    sample_count: int
    accuracy: float
    log_loss: float
    brier_score: float
    ranked_probability_score: float
    expected_calibration_error: float
    calibration_bins: tuple[CalibrationBin, ...]


def _actual_vector(result: MatchResult) -> tuple[float, float, float]:
    return tuple(1.0 if outcome == result else 0.0 for outcome in RESULT_ORDER)  # type: ignore[return-value]


def _actual_index(result: MatchResult) -> int:
    return RESULT_ORDER.index(result)


def _calibration_bins(
    predictions: tuple[MatchPrediction, ...], *, bin_count: int
) -> tuple[CalibrationBin, ...]:
    if bin_count <= 0:
        raise ValueError("calibration bin count must be positive")
    buckets: list[list[tuple[float, float]]] = [[] for _ in range(bin_count)]
    for prediction in predictions:
        actual = _actual_vector(prediction.actual_result)
        for probability, observed in zip(prediction.probabilities.as_tuple(), actual, strict=True):
            index = min(int(probability * bin_count), bin_count - 1)
            buckets[index].append((probability, observed))

    result: list[CalibrationBin] = []
    for index, bucket in enumerate(buckets):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        if not bucket:
            result.append(
                CalibrationBin(
                    lower=lower,
                    upper=upper,
                    count=0,
                    mean_probability=None,
                    observed_frequency=None,
                )
            )
            continue
        result.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=len(bucket),
                mean_probability=sum(item[0] for item in bucket) / len(bucket),
                observed_frequency=sum(item[1] for item in bucket) / len(bucket),
            )
        )
    return tuple(result)


def evaluate_predictions(
    predictions: tuple[MatchPrediction, ...], *, calibration_bin_count: int = 10
) -> EvaluationMetrics:
    """Evaluate ordered H/D/A probabilities without reducing them to picks alone."""

    if not predictions:
        raise ValueError("at least one prediction is required")
    accuracy_total = 0
    log_loss_total = 0.0
    brier_total = 0.0
    ranked_total = 0.0
    epsilon = 1e-15
    for prediction in predictions:
        probabilities = prediction.probabilities.as_tuple()
        actual = _actual_vector(prediction.actual_result)
        predicted_index = max(range(len(probabilities)), key=probabilities.__getitem__)
        accuracy_total += int(predicted_index == _actual_index(prediction.actual_result))
        true_probability = probabilities[_actual_index(prediction.actual_result)]
        log_loss_total -= math.log(max(epsilon, min(1.0 - epsilon, true_probability)))
        brier_total += sum(
            (probability - observed) ** 2
            for probability, observed in zip(probabilities, actual, strict=True)
        )
        probability_cumulative = 0.0
        actual_cumulative = 0.0
        ranked_match = 0.0
        for index in range(len(probabilities) - 1):
            probability_cumulative += probabilities[index]
            actual_cumulative += actual[index]
            ranked_match += (probability_cumulative - actual_cumulative) ** 2
        ranked_total += ranked_match / (len(probabilities) - 1)

    bins = _calibration_bins(predictions, bin_count=calibration_bin_count)
    observation_count = len(predictions) * len(RESULT_ORDER)
    calibration_error = sum(
        (calibration_bin.count / observation_count)
        * abs(
            (calibration_bin.mean_probability or 0.0) - (calibration_bin.observed_frequency or 0.0)
        )
        for calibration_bin in bins
    )
    count = len(predictions)
    return EvaluationMetrics(
        sample_count=count,
        accuracy=accuracy_total / count,
        log_loss=log_loss_total / count,
        brier_score=brier_total / count,
        ranked_probability_score=ranked_total / count,
        expected_calibration_error=calibration_error,
        calibration_bins=bins,
    )


def fixed_probability_predictions(
    records: tuple[MatchRecord, ...], probabilities: ResultProbabilities
) -> tuple[MatchPrediction, ...]:
    return tuple(
        MatchPrediction(
            match_uuid=record.match_uuid,
            season=record.season,
            kickoff_at=record.kickoff_at.isoformat(),
            actual_result=record.result,
            probabilities=probabilities,
        )
        for record in records
    )
