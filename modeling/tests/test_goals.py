"""Dynamic Poisson and Dixon-Coles behavior."""

from datetime import UTC, datetime

import pytest
from prem_engine_modeling.goals import (
    DynamicGoalModel,
    GoalModelConfig,
    forecast_from_rates,
)

from .helpers import club_uuid, match_record


def test_score_matrix_and_outcome_probabilities_are_normalized() -> None:
    forecast = forecast_from_rates(1.8, 0.9, dixon_coles_rho=-0.08)

    assert sum(sum(row) for row in forecast.score_matrix) == pytest.approx(1.0)
    assert sum(forecast.outcome_probabilities.as_tuple()) == pytest.approx(1.0)
    assert forecast.outcome_probabilities.home > forecast.outcome_probabilities.away
    assert forecast.top_scorelines(1)[0].probability == max(
        probability for row in forecast.score_matrix for probability in row
    )


def test_dixon_coles_changes_low_scores_without_invalid_probabilities() -> None:
    independent = forecast_from_rates(1.4, 1.1, dixon_coles_rho=0.0)
    corrected = forecast_from_rates(1.4, 1.1, dixon_coles_rho=-0.12)

    assert corrected.probability(0, 0) > independent.probability(0, 0)
    assert corrected.probability(1, 1) > independent.probability(1, 1)
    assert corrected.probability(0, 1) < independent.probability(0, 1)
    assert all(value >= 0.0 for row in corrected.score_matrix for value in row)


def test_home_advantage_update_and_season_carryover() -> None:
    config = GoalModelConfig(learning_rate=0.1, home_advantage=0.2, season_carryover=0.5)
    model = DynamicGoalModel(config)
    alpha = club_uuid("Alpha")
    beta = club_uuid("Beta")
    model.begin_season("2024/25")

    initial = model.predict(alpha, beta)
    assert initial.expected_home_goals > initial.expected_away_goals
    model.update(
        match_record(
            identifier="large-home-win",
            season="2024/25",
            kickoff_at=datetime(2024, 8, 1, tzinfo=UTC),
            home_goals=5,
            away_goals=0,
        )
    )
    updated = model.predict(alpha, beta)
    assert updated.expected_home_goals > initial.expected_home_goals
    previous_attack = model.attack_snapshot()[alpha]

    model.begin_season("2025/26")
    assert model.attack_snapshot()[alpha] == pytest.approx(previous_attack * 0.5)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"learning_rate": 0.0}, "learning rate"),
        ({"base_goal_rate": 0.0}, "base goal rate"),
        ({"dixon_coles_rho": -0.5}, "rho"),
        ({"season_carryover": 1.5}, "carryover"),
        ({"score_limit": 2}, "score limit"),
    ],
)
def test_invalid_goal_config_is_rejected(values: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        GoalModelConfig(**values)  # type: ignore[arg-type]


def test_forecast_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="positive"):
        forecast_from_rates(0.0, 1.0)
    forecast = forecast_from_rates(1.0, 1.0)
    with pytest.raises(ValueError, match="negative"):
        forecast.probability(-1, 0)
    with pytest.raises(ValueError, match="positive"):
        forecast.top_scorelines(0)
    assert forecast.probability(99, 99) == 0.0
