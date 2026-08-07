"""Dynamic Poisson goal model with a Dixon-Coles low-score correction."""

from __future__ import annotations

import math
from dataclasses import dataclass

from prem_engine_modeling.data import MatchRecord
from prem_engine_modeling.elo import ResultProbabilities

MIN_EXPECTED_GOALS = 0.05
MAX_EXPECTED_GOALS = 8.0
MAX_STRENGTH = 1.5
DEFAULT_SCORE_LIMIT = 10


@dataclass(frozen=True, order=True)
class GoalModelConfig:
    """Configuration for deterministic online attack and defence ratings."""

    learning_rate: float = 0.03
    base_goal_rate: float = 1.35
    home_advantage: float = 0.18
    dixon_coles_rho: float = -0.08
    season_carryover: float = 0.90
    score_limit: int = DEFAULT_SCORE_LIMIT

    def __post_init__(self) -> None:
        if not 0.0 < self.learning_rate <= 0.25:
            raise ValueError("learning rate must be in (0, 0.25]")
        if not 0.1 <= self.base_goal_rate <= 5.0:
            raise ValueError("base goal rate must be in [0.1, 5]")
        if not -0.5 <= self.home_advantage <= 0.75:
            raise ValueError("home advantage must be in [-0.5, 0.75]")
        if not -0.2 <= self.dixon_coles_rho <= 0.2:
            raise ValueError("Dixon-Coles rho must be in [-0.2, 0.2]")
        if not 0.0 <= self.season_carryover <= 1.0:
            raise ValueError("season carryover must be in [0, 1]")
        if not 5 <= self.score_limit <= 15:
            raise ValueError("score limit must be in [5, 15]")


@dataclass(frozen=True)
class ScorelineProbability:
    home_goals: int
    away_goals: int
    probability: float


@dataclass(frozen=True)
class GoalForecast:
    expected_home_goals: float
    expected_away_goals: float
    score_matrix: tuple[tuple[float, ...], ...]
    outcome_probabilities: ResultProbabilities

    def probability(self, home_goals: int, away_goals: int) -> float:
        if home_goals < 0 or away_goals < 0:
            raise ValueError("goals cannot be negative")
        if home_goals >= len(self.score_matrix) or away_goals >= len(self.score_matrix[0]):
            return 0.0
        return self.score_matrix[home_goals][away_goals]

    def top_scorelines(self, count: int = 5) -> tuple[ScorelineProbability, ...]:
        if count <= 0:
            raise ValueError("scoreline count must be positive")
        scorelines = (
            ScorelineProbability(home, away, probability)
            for home, row in enumerate(self.score_matrix)
            for away, probability in enumerate(row)
        )
        return tuple(
            sorted(
                scorelines, key=lambda item: (-item.probability, item.home_goals, item.away_goals)
            )[:count]
        )


def _poisson_probabilities(rate: float, limit: int) -> tuple[float, ...]:
    values = [math.exp(-rate)]
    for goals in range(1, limit + 1):
        values.append(values[-1] * rate / goals)
    return tuple(values)


def _dixon_coles_tau(
    home_goals: int, away_goals: int, home_rate: float, away_rate: float, rho: float
) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1.0 - home_rate * away_rate * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + home_rate * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + away_rate * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def forecast_from_rates(
    expected_home_goals: float,
    expected_away_goals: float,
    *,
    dixon_coles_rho: float = 0.0,
    score_limit: int = DEFAULT_SCORE_LIMIT,
) -> GoalForecast:
    """Convert two scoring intensities into a normalized score and outcome distribution."""

    if expected_home_goals <= 0.0 or expected_away_goals <= 0.0:
        raise ValueError("expected goals must be positive")
    home_probabilities = _poisson_probabilities(expected_home_goals, score_limit)
    away_probabilities = _poisson_probabilities(expected_away_goals, score_limit)
    unnormalized: list[list[float]] = []
    for home_goals, home_probability in enumerate(home_probabilities):
        row: list[float] = []
        for away_goals, away_probability in enumerate(away_probabilities):
            correction = _dixon_coles_tau(
                home_goals,
                away_goals,
                expected_home_goals,
                expected_away_goals,
                dixon_coles_rho,
            )
            row.append(max(0.0, home_probability * away_probability * correction))
        unnormalized.append(row)
    total = sum(sum(row) for row in unnormalized)
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("invalid scoreline probability mass")
    matrix = tuple(tuple(value / total for value in row) for row in unnormalized)
    home = sum(
        probability
        for home_goals, row in enumerate(matrix)
        for away_goals, probability in enumerate(row)
        if home_goals > away_goals
    )
    draw = sum(row[index] for index, row in enumerate(matrix))
    away = max(0.0, 1.0 - home - draw)
    return GoalForecast(
        expected_home_goals=expected_home_goals,
        expected_away_goals=expected_away_goals,
        score_matrix=matrix,
        outcome_probabilities=ResultProbabilities(home=home, draw=draw, away=away),
    )


class DynamicGoalModel:
    """Online Poisson attack/defence strengths suitable for strict walk-forward use."""

    def __init__(self, config: GoalModelConfig) -> None:
        self.config = config
        self._attack: dict[str, float] = {}
        self._defence: dict[str, float] = {}
        self._current_season: str | None = None

    @classmethod
    def from_snapshot(
        cls,
        *,
        config: GoalModelConfig,
        attack: dict[str, float],
        defence: dict[str, float],
        current_season: str,
    ) -> DynamicGoalModel:
        model = cls(config)
        model._attack = dict(attack)
        model._defence = dict(defence)
        model._current_season = current_season
        return model

    def begin_season(self, season: str) -> None:
        if self._current_season is not None and season != self._current_season:
            self._attack = {
                club: strength * self.config.season_carryover
                for club, strength in self._attack.items()
            }
            self._defence = {
                club: strength * self.config.season_carryover
                for club, strength in self._defence.items()
            }
        self._current_season = season

    def _strength(self, values: dict[str, float], club_uuid: str) -> float:
        return values.get(club_uuid, 0.0)

    def expected_goals(self, home_club_uuid: str, away_club_uuid: str) -> tuple[float, float]:
        home_log_rate = (
            math.log(self.config.base_goal_rate)
            + self.config.home_advantage
            + self._strength(self._attack, home_club_uuid)
            - self._strength(self._defence, away_club_uuid)
        )
        away_log_rate = (
            math.log(self.config.base_goal_rate)
            + self._strength(self._attack, away_club_uuid)
            - self._strength(self._defence, home_club_uuid)
        )
        return (
            min(MAX_EXPECTED_GOALS, max(MIN_EXPECTED_GOALS, math.exp(home_log_rate))),
            min(MAX_EXPECTED_GOALS, max(MIN_EXPECTED_GOALS, math.exp(away_log_rate))),
        )

    def predict(self, home_club_uuid: str, away_club_uuid: str) -> GoalForecast:
        home_rate, away_rate = self.expected_goals(home_club_uuid, away_club_uuid)
        return forecast_from_rates(
            home_rate,
            away_rate,
            dixon_coles_rho=self.config.dixon_coles_rho,
            score_limit=self.config.score_limit,
        )

    def update(self, match: MatchRecord) -> None:
        expected_home, expected_away = self.expected_goals(
            match.home_club_uuid, match.away_club_uuid
        )
        home_error = max(-3.0, min(3.0, match.home_goals - expected_home))
        away_error = max(-3.0, min(3.0, match.away_goals - expected_away))
        step = self.config.learning_rate / 2.0
        self._adjust(self._attack, match.home_club_uuid, step * home_error)
        self._adjust(self._defence, match.away_club_uuid, -step * home_error)
        self._adjust(self._attack, match.away_club_uuid, step * away_error)
        self._adjust(self._defence, match.home_club_uuid, -step * away_error)

    @staticmethod
    def _adjust(values: dict[str, float], club_uuid: str, change: float) -> None:
        values[club_uuid] = min(
            MAX_STRENGTH, max(-MAX_STRENGTH, values.get(club_uuid, 0.0) + change)
        )

    def attack_snapshot(self) -> dict[str, float]:
        return dict(sorted(self._attack.items()))

    def defence_snapshot(self) -> dict[str, float]:
        return dict(sorted(self._defence.items()))

    @property
    def current_season(self) -> str | None:
        return self._current_season
