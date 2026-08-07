"""Goal, scoreline, and derived outcome metrics."""

from datetime import UTC, datetime

import pytest
from prem_engine_modeling.goal_evaluation import evaluate_goal_predictions, fixed_goal_predictions
from prem_engine_modeling.goals import forecast_from_rates

from .helpers import match_record


def test_accurate_goal_forecast_beats_bad_forecast() -> None:
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
    )
    reasonable = evaluate_goal_predictions(
        fixed_goal_predictions(records, forecast_from_rates(1.5, 0.8))
    )
    bad = evaluate_goal_predictions(fixed_goal_predictions(records, forecast_from_rates(0.2, 4.0)))

    assert reasonable.mean_goal_mae < bad.mean_goal_mae
    assert reasonable.scoreline_log_loss < bad.scoreline_log_loss
    assert reasonable.outcome_metrics.log_loss < bad.outcome_metrics.log_loss
    assert reasonable.sample_count == 2
    assert reasonable.mean_actual_home_goals == pytest.approx(1.5)


def test_goal_evaluation_requires_predictions() -> None:
    with pytest.raises(ValueError, match="at least one"):
        evaluate_goal_predictions(())
