"""Generate the deterministic Phase 13 browser-preview payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from prem_engine_modeling.goals import forecast_from_rates
from prem_engine_modeling.simulation import (
    SimulationForecast,
    SimulationLineup,
    SimulationPlayer,
    generate_stored_simulation,
    validate_simulation_consistency,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
Position = Literal["GK", "DEF", "MID", "FWD"]


def _players(
    club_key: str,
    names: tuple[str, ...],
    positions: tuple[Position, ...],
    shirt_numbers: tuple[int, ...],
) -> tuple[SimulationPlayer, ...]:
    return tuple(
        SimulationPlayer(
            player_uuid=f"preview-{club_key}-player-{index:02d}",
            name=name,
            position=position,
            shirt_number=shirt_number,
        )
        for index, (name, position, shirt_number) in enumerate(
            zip(names, positions, shirt_numbers, strict=True), 1
        )
    )


def _lineups() -> tuple[SimulationLineup, SimulationLineup]:
    starters: tuple[Position, ...] = (
        "GK",
        "DEF",
        "DEF",
        "DEF",
        "DEF",
        "MID",
        "MID",
        "MID",
        "FWD",
        "FWD",
        "FWD",
    )
    substitutes: tuple[Position, ...] = ("GK", "DEF", "MID", "MID", "FWD")
    home = SimulationLineup(
        club_uuid="preview-northbridge-united",
        club_name="Northbridge United",
        short_name="NBU",
        formation="4-3-3",
        starters=_players(
            "nbu",
            (
                "Callum Reed",
                "Milo Bennett",
                "Jonah Clarke",
                "Theo Marsh",
                "Elias Ward",
                "Noah Foster",
                "Ruben Cole",
                "Isaac Hughes",
                "Leon Price",
                "Aaron Wells",
                "Dylan Shaw",
            ),
            starters,
            (1, 2, 5, 6, 3, 8, 10, 14, 7, 9, 11),
        ),
        substitutes=_players(
            "nbu-sub",
            ("Owen Hart", "Samir Quinn", "Kai Brooks", "Luca Green", "Jamie Cross"),
            substitutes,
            (13, 17, 18, 20, 23),
        ),
    )
    away = SimulationLineup(
        club_uuid="preview-docklands-city",
        club_name="Docklands City",
        short_name="DOC",
        formation="4-2-3-1",
        starters=_players(
            "doc",
            (
                "Finn Turner",
                "Micah Ross",
                "Adam Blake",
                "Ryan Stone",
                "Ben Taylor",
                "Mateo King",
                "Zane Morris",
                "Ellis Young",
                "Nico Perry",
                "Harvey Wood",
                "Joel Grant",
            ),
            starters,
            (1, 2, 4, 5, 21, 6, 8, 7, 10, 11, 9),
        ),
        substitutes=_players(
            "doc-sub",
            ("Alex Dean", "Kian Bell", "Evan Fox", "Max Hill", "Ari Cooper"),
            substitutes,
            (12, 15, 16, 19, 24),
        ),
    )
    return home, away


def _preview() -> dict[str, object]:
    expected_home_goals = 1.72
    expected_away_goals = 1.31
    goal_forecast = forecast_from_rates(
        expected_home_goals,
        expected_away_goals,
        dixon_coles_rho=-0.08,
    )
    home, away = _lineups()
    forecast = SimulationForecast(
        match_uuid="13b71183-2f67-5a5c-a79f-faf49c88230b",
        prediction_version_uuid="f23c0300-8af7-5783-b50d-c58ed860551b",
        feature_cutoff_at="2026-08-14T14:00:00Z",
        locked_at="2026-08-14T14:01:12Z",
        outcome_model_version="goals-v1-156511483a94",
        statistics_model_version="detailed-statistics-v1-42e73adec486",
        expected_home_goals=expected_home_goals,
        expected_away_goals=expected_away_goals,
        score_matrix=goal_forecast.score_matrix,
        statistic_means={
            "home_half_time_goals": 0.72,
            "away_half_time_goals": 0.55,
            "home_shots": 13.8,
            "away_shots": 11.7,
            "home_shots_on_target": 4.67,
            "away_shots_on_target": 4.07,
            "home_corners": 5.4,
            "away_corners": 4.7,
            "home_fouls": 10.7,
            "away_fouls": 11.1,
            "home_yellow_cards": 1.8,
            "away_yellow_cards": 2.1,
            "home_red_cards": 0.06,
            "away_red_cards": 0.06,
        },
        home_lineup=home,
        away_lineup=away,
    )
    simulation = generate_stored_simulation(forecast, random_seed=13_082_026)
    validate_simulation_consistency(simulation)
    return {
        "preview": {
            "is_sample_data": True,
            "notice": (
                "Fixed fictional fixture generated to test the Phase 13 replay experience. "
                "Refreshing the page replays the same locked simulation."
            ),
            "competition": "Premier League forecast preview",
            "matchweek": 1,
            "kickoff_at": "2026-08-15T14:00:00Z",
            "venue": "Engine Park",
            "presentation_duration_seconds": 60,
            "first_half_seconds": 25,
            "half_time_seconds": 10,
            "second_half_seconds": 25,
        },
        "simulation": simulation.as_dict(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "frontend" / "src" / "data" / "simulation-preview.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    preview = _preview()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(preview, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    simulation = preview["simulation"]
    if not isinstance(simulation, dict):
        raise TypeError("preview simulation must be a mapping")
    print("PREM ENGINE - PHASE 13 SIMULATION PREVIEW")
    print("=" * 72)
    print(f"Result       {simulation['home_goals']}-{simulation['away_goals']}")
    print(f"Events       {len(simulation['events'])}")
    print(f"Random seed  {simulation['random_seed']}")
    print(f"Checksum     {simulation['checksum']}")
    print(f"Written to   {args.output.resolve()}")
    print("=" * 72)


if __name__ == "__main__":
    main()
