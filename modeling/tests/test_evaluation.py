"""Metric definitions for probabilistic match results."""

from datetime import UTC, datetime

import pytest
from prem_engine_modeling.elo import ResultProbabilities
from prem_engine_modeling.evaluation import evaluate_predictions, fixed_probability_predictions

from .helpers import match_record


def test_perfect_probabilities_beat_uniform_probabilities() -> None:
    records = (
        match_record(
            identifier="home",
            season="2024/25",
            kickoff_at=datetime(2024, 8, 1, tzinfo=UTC),
            home_goals=2,
            away_goals=0,
        ),
        match_record(
            identifier="draw",
            season="2024/25",
            kickoff_at=datetime(2024, 8, 2, tzinfo=UTC),
            home_goals=1,
            away_goals=1,
        ),
        match_record(
            identifier="away",
            season="2024/25",
            kickoff_at=datetime(2024, 8, 3, tzinfo=UTC),
            home_goals=0,
            away_goals=2,
        ),
    )
    uniform = evaluate_predictions(
        fixed_probability_predictions(records, ResultProbabilities(1 / 3, 1 / 3, 1 / 3))
    )
    strong_home = evaluate_predictions(
        fixed_probability_predictions((records[0],), ResultProbabilities(0.9, 0.05, 0.05))
    )

    assert uniform.log_loss == pytest.approx(1.0986122886681098)
    assert uniform.brier_score == pytest.approx(2 / 3)
    assert strong_home.log_loss < uniform.log_loss
    assert len(uniform.calibration_bins) == 10
    assert sum(calibration_bin.count for calibration_bin in uniform.calibration_bins) == 9


def test_evaluation_requires_predictions_and_positive_bins() -> None:
    with pytest.raises(ValueError, match="at least one"):
        evaluate_predictions(())
    record = match_record(
        identifier="one",
        season="2024/25",
        kickoff_at=datetime(2024, 8, 1, tzinfo=UTC),
    )
    predictions = fixed_probability_predictions((record,), ResultProbabilities(0.5, 0.25, 0.25))
    with pytest.raises(ValueError, match="bin count"):
        evaluate_predictions(predictions, calibration_bin_count=0)
