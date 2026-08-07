"""Three-outcome Elo probability and update behavior."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from prem_engine_modeling.elo import EloConfig, EloModel

from .helpers import club_uuid, match_record


def test_home_advantage_produces_valid_ordered_probabilities() -> None:
    neutral = EloModel(EloConfig(home_advantage=0))
    advantaged = EloModel(EloConfig(home_advantage=80))

    neutral_probabilities = neutral.predict(club_uuid("Alpha"), club_uuid("Beta"))
    home_probabilities = advantaged.predict(club_uuid("Alpha"), club_uuid("Beta"))

    assert sum(home_probabilities.as_tuple()) == pytest.approx(1.0)
    assert neutral_probabilities.home == pytest.approx(neutral_probabilities.away)
    assert home_probabilities.home > neutral_probabilities.home
    assert home_probabilities.away < neutral_probabilities.away


def test_rating_update_is_zero_sum_and_margin_weight_is_effective() -> None:
    match = match_record(
        identifier="margin",
        season="2020/21",
        kickoff_at=datetime(2020, 8, 1, tzinfo=UTC),
        home_goals=4,
        away_goals=0,
    )
    plain = EloModel(EloConfig(home_advantage=0, margin_weight=0))
    weighted = EloModel(EloConfig(home_advantage=0, margin_weight=0.5))

    plain_delta = plain.update(match)
    weighted_delta = weighted.update(match)

    assert plain.rating(match.home_club_uuid) + plain.rating(match.away_club_uuid) == 3000
    assert weighted_delta > plain_delta > 0


def test_season_carryover_regresses_ratings_and_snapshot_restores_inference() -> None:
    config = EloConfig(home_advantage=0, season_carryover=0.5)
    model = EloModel(config)
    match = match_record(
        identifier="carryover",
        season="2020/21",
        kickoff_at=datetime(2020, 8, 1, tzinfo=UTC),
    )
    model.begin_season("2020/21")
    model.update(match)
    prior = model.rating(match.home_club_uuid)
    model.begin_season("2021/22")

    assert model.rating(match.home_club_uuid) == pytest.approx(1500 + 0.5 * (prior - 1500))
    restored = EloModel.from_snapshot(
        config=config,
        ratings=model.ratings_snapshot(),
        current_season="2021/22",
    )
    assert restored.predict(match.home_club_uuid, match.away_club_uuid) == model.predict(
        match.home_club_uuid, match.away_club_uuid
    )


@pytest.mark.parametrize(
    "config",
    [
        EloConfig(k_factor=20),
        replace(EloConfig(), home_advantage=0),
    ],
)
def test_configuration_is_immutable_and_constructible(config: EloConfig) -> None:
    assert config.k_factor > 0


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        EloConfig(k_factor=0)
    with pytest.raises(ValueError):
        EloConfig(season_carryover=1.1)
