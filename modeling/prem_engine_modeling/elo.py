"""Deterministic three-outcome Elo ratings for football matches."""

from __future__ import annotations

import math
from dataclasses import dataclass

from prem_engine_modeling.data import MatchRecord, MatchResult
from prem_engine_modeling.validation import validate_result_probabilities


@dataclass(frozen=True, order=True)
class EloConfig:
    k_factor: float = 20.0
    home_advantage: float = 80.0
    draw_propensity: float = 0.65
    margin_weight: float = 0.25
    season_carryover: float = 0.85
    initial_rating: float = 1500.0
    rating_scale: float = 400.0

    def __post_init__(self) -> None:
        if self.k_factor <= 0 or self.rating_scale <= 0:
            raise ValueError("Elo k-factor and rating scale must be positive")
        if self.draw_propensity <= 0:
            raise ValueError("draw propensity must be positive")
        if self.margin_weight < 0:
            raise ValueError("margin weight cannot be negative")
        if not 0 <= self.season_carryover <= 1:
            raise ValueError("season carryover must be between zero and one")


@dataclass(frozen=True)
class ResultProbabilities:
    home: float
    draw: float
    away: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.home, self.draw, self.away)


class EloModel:
    """Online rating model using Davidson's draw extension to Bradley-Terry."""

    def __init__(self, config: EloConfig) -> None:
        self.config = config
        self._ratings: dict[str, float] = {}
        self._current_season: str | None = None

    @classmethod
    def from_snapshot(
        cls,
        *,
        config: EloConfig,
        ratings: dict[str, float],
        current_season: str,
    ) -> EloModel:
        """Restore a validated immutable training artifact for inference."""

        if not ratings or any(not math.isfinite(rating) for rating in ratings.values()):
            raise ValueError("rating snapshot must contain finite club ratings")
        model = cls(config)
        model._ratings = dict(ratings)
        model._current_season = current_season
        return model

    def rating(self, club_uuid: str) -> float:
        return self._ratings.get(club_uuid, self.config.initial_rating)

    def begin_season(self, season: str) -> None:
        """Regress established ratings at each season boundary for recency."""

        if self._current_season is None:
            self._current_season = season
            return
        if season == self._current_season:
            return
        base = self.config.initial_rating
        self._ratings = {
            club_uuid: base + self.config.season_carryover * (rating - base)
            for club_uuid, rating in self._ratings.items()
        }
        self._current_season = season

    def predict(self, home_club_uuid: str, away_club_uuid: str) -> ResultProbabilities:
        home_rating = self.rating(home_club_uuid)
        away_rating = self.rating(away_club_uuid)
        difference = max(
            -1200.0,
            min(1200.0, home_rating + self.config.home_advantage - away_rating),
        )
        strength_ratio = 10.0 ** (difference / self.config.rating_scale)
        draw_term = self.config.draw_propensity * math.sqrt(strength_ratio)
        denominator = strength_ratio + draw_term + 1.0
        probabilities = ResultProbabilities(
            home=strength_ratio / denominator,
            draw=draw_term / denominator,
            away=1.0 / denominator,
        )
        validate_result_probabilities(probabilities.as_tuple())
        return probabilities

    @staticmethod
    def _home_score(result: MatchResult) -> float:
        return {"H": 1.0, "D": 0.5, "A": 0.0}[result]

    def update(self, match: MatchRecord) -> float:
        """Apply one completed real match and return the signed home-rating change."""

        probabilities = self.predict(match.home_club_uuid, match.away_club_uuid)
        expected_score = probabilities.home + 0.5 * probabilities.draw
        goal_margin = abs(match.home_goals - match.away_goals)
        margin_multiplier = 1.0 + self.config.margin_weight * math.log1p(goal_margin)
        delta = (
            self.config.k_factor
            * margin_multiplier
            * (self._home_score(match.result) - expected_score)
        )
        self._ratings[match.home_club_uuid] = self.rating(match.home_club_uuid) + delta
        self._ratings[match.away_club_uuid] = self.rating(match.away_club_uuid) - delta
        return delta

    def ratings_snapshot(self) -> dict[str, float]:
        return dict(sorted(self._ratings.items()))
