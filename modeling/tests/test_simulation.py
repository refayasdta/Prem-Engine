"""Phase 13 deterministic quick-match simulation tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from prem_engine_modeling.goals import forecast_from_rates
from prem_engine_modeling.simulation import (
    SimulationForecast,
    SimulationLineup,
    SimulationPlayer,
    generate_stored_simulation,
    validate_simulation_consistency,
)


def _lineup(side: str) -> SimulationLineup:
    positions = ("GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "FWD", "FWD", "FWD")
    starters = tuple(
        SimulationPlayer(
            player_uuid=f"{side}-starter-{index}",
            name=f"{side.title()} Player {index}",
            position=position,  # type: ignore[arg-type]
            shirt_number=index,
        )
        for index, position in enumerate(positions, 1)
    )
    substitutes = tuple(
        SimulationPlayer(
            player_uuid=f"{side}-substitute-{index}",
            name=f"{side.title()} Substitute {index}",
            position="MID",
            shirt_number=index + 20,
        )
        for index in range(1, 6)
    )
    return SimulationLineup(
        club_uuid=f"{side}-club",
        club_name=f"{side.title()} Athletic",
        short_name=side[:3].upper(),
        formation="4-3-3",
        starters=starters,
        substitutes=substitutes,
    )


def _forecast() -> SimulationForecast:
    goal_forecast = forecast_from_rates(1.72, 1.31, dixon_coles_rho=-0.08)
    means = {
        "home_half_time_goals": 0.72,
        "away_half_time_goals": 0.55,
        "home_shots": 13.8,
        "away_shots": 11.7,
        "home_shots_on_target": 4.7,
        "away_shots_on_target": 4.1,
        "home_corners": 5.4,
        "away_corners": 4.7,
        "home_fouls": 10.7,
        "away_fouls": 11.1,
        "home_yellow_cards": 1.8,
        "away_yellow_cards": 2.1,
        "home_red_cards": 0.06,
        "away_red_cards": 0.06,
    }
    return SimulationForecast(
        match_uuid="match-phase-13",
        prediction_version_uuid="prediction-phase-13",
        feature_cutoff_at="2026-08-10T12:00:00Z",
        locked_at="2026-08-10T12:01:00Z",
        outcome_model_version="goals-v1-test",
        statistics_model_version="statistics-v1-test",
        expected_home_goals=1.72,
        expected_away_goals=1.31,
        score_matrix=goal_forecast.score_matrix,
        statistic_means=means,
        home_lineup=_lineup("home"),
        away_lineup=_lineup("away"),
    )


def test_same_seed_produces_the_same_locked_payload() -> None:
    first = generate_stored_simulation(_forecast(), random_seed=13_082_026)
    second = generate_stored_simulation(_forecast(), random_seed=13_082_026)

    assert first == second
    assert first.checksum == second.checksum
    assert len(first.checksum) == 64
    validate_simulation_consistency(first)


def test_different_seed_changes_the_locked_payload() -> None:
    first = generate_stored_simulation(_forecast(), random_seed=13_082_026)
    second = generate_stored_simulation(_forecast(), random_seed=13_082_027)

    assert first.checksum != second.checksum


def test_score_statistics_and_events_are_internally_consistent() -> None:
    payload = generate_stored_simulation(_forecast(), random_seed=13_082_026)

    assert payload.events[0].event_type == "kickoff"
    assert payload.events[-1].event_type == "full_time"
    assert payload.events[-1].home_score == payload.home_goals
    assert payload.events[-1].away_score == payload.away_goals
    for side in ("home", "away"):
        assert payload.statistics[f"{side}_shots_on_target"] <= payload.statistics[f"{side}_shots"]
        assert payload.statistics[f"{side}_half_time_goals"] <= getattr(payload, f"{side}_goals")
    assert (
        pytest.approx(
            payload.home_win_probability + payload.draw_probability + payload.away_win_probability
        )
        == 1.0
    )
    validate_simulation_consistency(payload)


def test_checksum_detects_tampering() -> None:
    payload = generate_stored_simulation(_forecast(), random_seed=13_082_026)

    with pytest.raises(ValueError, match="checksum"):
        validate_simulation_consistency(replace(payload, home_goals=payload.home_goals + 1))


def test_lineup_contract_rejects_too_few_starters() -> None:
    lineup = _lineup("home")

    with pytest.raises(ValueError, match="11 starters"):
        replace(lineup, starters=lineup.starters[:-1])


def test_zero_statistic_means_generate_zero_events() -> None:
    forecast = _forecast()
    zero_means = {key: 0.0 for key in forecast.statistic_means}
    payload = generate_stored_simulation(
        replace(forecast, statistic_means=zero_means), random_seed=3
    )

    assert all(value >= 0 for value in payload.statistics.values())
    validate_simulation_consistency(payload)
