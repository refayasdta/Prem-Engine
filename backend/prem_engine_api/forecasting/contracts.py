"""Validated contracts passed into the atomic forecast writer."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

PlayerPosition = Literal["GK", "DEF", "MID", "FWD"]

SIMULATION_STATISTIC_NAMES = tuple(
    f"{side}_{name}"
    for side in ("home", "away")
    for name in (
        "half_time_goals",
        "shots",
        "shots_on_target",
        "corners",
        "fouls",
        "yellow_cards",
        "red_cards",
    )
)


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")


@dataclass(frozen=True)
class FeatureSnapshotInput:
    schema_version: str
    feature_cutoff_at: datetime
    latest_source_observed_at: datetime | None
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.schema_version.strip():
            raise ValueError("feature snapshot schema version is required")
        _require_aware(self.feature_cutoff_at, "feature cutoff")
        if self.latest_source_observed_at is not None:
            _require_aware(self.latest_source_observed_at, "latest source observation")
            if self.latest_source_observed_at >= self.feature_cutoff_at:
                raise ValueError("feature snapshot contains data at or after its cutoff")
        try:
            json.dumps(self.payload, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise ValueError("feature snapshot payload must be finite JSON data") from error


@dataclass(frozen=True)
class LineupPlayer:
    player_uuid: UUID
    name: str
    position: PlayerPosition
    shirt_number: int
    shirt_number_source: Literal["observed", "presentation_slot"]
    starting_probability: float
    availability_probability: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("lineup player name is required")
        if not 1 <= self.shirt_number <= 99:
            raise ValueError("lineup shirt number must be between 1 and 99")
        for field, value in (
            ("starting probability", self.starting_probability),
            ("availability probability", self.availability_probability),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{field} must be in [0, 1]")


@dataclass(frozen=True)
class TeamLineup:
    club_uuid: UUID
    club_name: str
    short_name: str
    formation: str
    starters: tuple[LineupPlayer, ...]
    substitutes: tuple[LineupPlayer, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not self.club_name.strip() or not self.short_name.strip() or not self.formation.strip():
            raise ValueError("lineup club names and formation are required")
        if len(self.starters) != 11 or len(self.substitutes) < 3:
            raise ValueError("forecast lineups require 11 starters and at least 3 substitutes")
        identifiers = [item.player_uuid for item in self.starters + self.substitutes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("forecast lineup player UUIDs must be unique")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("lineup confidence must be in [0, 1]")


@dataclass(frozen=True)
class ModelForecast:
    outcome_model_version: str
    statistics_model_version: str
    expected_home_goals: float
    expected_away_goals: float
    score_matrix: tuple[tuple[float, ...], ...]
    statistic_means: dict[str, float]
    statistic_intervals_90: dict[str, tuple[float, float]]

    def __post_init__(self) -> None:
        if not self.outcome_model_version or not self.statistics_model_version:
            raise ValueError("both model versions are required")
        if self.expected_home_goals <= 0.0 or self.expected_away_goals <= 0.0:
            raise ValueError("expected goals must be positive")
        if not self.score_matrix or any(
            len(row) != len(self.score_matrix[0]) for row in self.score_matrix
        ):
            raise ValueError("score matrix must be non-empty and rectangular")
        probabilities = [value for row in self.score_matrix for value in row]
        if any(not math.isfinite(value) or value < 0.0 for value in probabilities):
            raise ValueError("score matrix contains invalid probabilities")
        if not math.isclose(sum(probabilities), 1.0, abs_tol=1e-8):
            raise ValueError("score matrix probabilities must sum to one")
        missing = set(SIMULATION_STATISTIC_NAMES).difference(self.statistic_means)
        if missing:
            raise ValueError(f"forecast statistics are incomplete: {sorted(missing)}")
        for name in SIMULATION_STATISTIC_NAMES:
            mean = self.statistic_means[name]
            interval = self.statistic_intervals_90.get(name)
            if not math.isfinite(mean) or mean < 0.0:
                raise ValueError(f"{name} mean must be finite and non-negative")
            if (
                interval is None
                or len(interval) != 2
                or interval[0] < 0.0
                or interval[1] < interval[0]
                or not all(math.isfinite(value) for value in interval)
            ):
                raise ValueError(f"{name} interval is invalid")


@dataclass(frozen=True)
class ForecastPackage:
    match_uuid: UUID
    feature_snapshot: FeatureSnapshotInput
    forecast: ModelForecast
    home_lineup: TeamLineup
    away_lineup: TeamLineup
    random_seed: int

    def __post_init__(self) -> None:
        if self.home_lineup.club_uuid == self.away_lineup.club_uuid:
            raise ValueError("forecast clubs must differ")
        if not 0 <= self.random_seed <= 2_147_483_647:
            raise ValueError("random seed must fit a signed 32-bit integer")
