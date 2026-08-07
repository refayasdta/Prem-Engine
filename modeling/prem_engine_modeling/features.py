"""Time-safe pre-match feature engineering for Phase 8."""

from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from typing import Any, Literal

from prem_engine_modeling.data import HistoricalDataset, MatchRecord
from prem_engine_modeling.elo import EloConfig, EloModel
from prem_engine_modeling.goals import DynamicGoalModel, GoalModelConfig

FEATURE_CONTRACT_VERSION = "prematch-features-v1"
DEFAULT_PREDICTION_LEAD = timedelta(hours=24)

REFERENCE_ELO_CONFIG = EloConfig(
    k_factor=20.0,
    home_advantage=80.0,
    draw_propensity=0.65,
    margin_weight=0.5,
    season_carryover=0.95,
)
REFERENCE_GOAL_CONFIG = GoalModelConfig(
    learning_rate=0.03,
    base_goal_rate=1.45,
    home_advantage=0.18,
    dixon_coles_rho=0.0,
    season_carryover=0.95,
)


@dataclass(frozen=True)
class FeaturePipelineConfig:
    prediction_lead: timedelta = DEFAULT_PREDICTION_LEAD
    elo: EloConfig = REFERENCE_ELO_CONFIG
    goals: GoalModelConfig = REFERENCE_GOAL_CONFIG

    def __post_init__(self) -> None:
        if self.prediction_lead <= timedelta(0):
            raise ValueError("prediction lead must be positive")


@dataclass(frozen=True)
class ResultObservation:
    kickoff_at: datetime
    available_after: datetime
    season: str
    venue: Literal["home", "away"]
    points: int
    goals_for: int
    goals_against: int
    expected_points: float


@dataclass(frozen=True)
class ScheduleObservation:
    kickoff_at: datetime
    season: str
    venue: Literal["home", "away"]


@dataclass(frozen=True)
class TeamFeatures:
    elo_rating: float
    goal_attack_strength: float
    goal_defence_strength: float
    history_match_count: int
    season_fixture_count: int
    form_sample_count: int
    points_last_3: int
    points_last_5: int
    points_last_10: int
    points_per_match_last_5: float | None
    goals_for_per_match_last_5: float | None
    goals_against_per_match_last_5: float | None
    goals_for_per_match_last_10: float | None
    goals_against_per_match_last_10: float | None
    goal_difference_per_match_last_5: float | None
    win_rate_last_5: float | None
    draw_rate_last_5: float | None
    loss_rate_last_5: float | None
    clean_sheet_rate_last_5: float | None
    failed_to_score_rate_last_5: float | None
    venue_points_per_match_last_5: float | None
    opponent_adjusted_points_last_5: float | None
    form_trend: float | None
    rest_days: float | None
    matches_last_7_days: int
    matches_last_14_days: int
    matches_last_30_days: int
    is_promoted: int
    promotion_status_known: int
    early_season: int
    history_confidence: float
    missing_form_last_5: int
    missing_rest: int


IDENTITY_COLUMNS = (
    "feature_contract_version",
    "match_uuid",
    "season",
    "feature_cutoff_at",
    "kickoff_at",
    "prediction_lead_hours",
    "latest_input_available_after",
    "available_result_count",
    "home_club_uuid",
    "home_club",
    "away_club_uuid",
    "away_club",
)
MODEL_OUTPUT_COLUMNS = (
    "elo_home_probability",
    "elo_draw_probability",
    "elo_away_probability",
    "goal_expected_home_goals",
    "goal_expected_away_goals",
    "goal_home_probability",
    "goal_draw_probability",
    "goal_away_probability",
)
TEAM_FEATURE_NAMES = tuple(field.name for field in fields(TeamFeatures))
TEAM_FEATURE_COLUMNS = tuple(
    f"{side}_{name}" for side in ("home", "away") for name in TEAM_FEATURE_NAMES
)
TARGET_COLUMNS = ("target_home_goals", "target_away_goals", "target_result")
PREMATCH_FEATURE_COLUMNS = MODEL_OUTPUT_COLUMNS + TEAM_FEATURE_COLUMNS
EXPORT_COLUMNS = IDENTITY_COLUMNS + PREMATCH_FEATURE_COLUMNS + TARGET_COLUMNS


@dataclass(frozen=True)
class PrematchFeatureRow:
    match: MatchRecord
    feature_cutoff_at: datetime
    latest_input_available_after: datetime | None
    available_result_count: int
    prediction_lead_hours: float
    elo_home_probability: float
    elo_draw_probability: float
    elo_away_probability: float
    goal_expected_home_goals: float
    goal_expected_away_goals: float
    goal_home_probability: float
    goal_draw_probability: float
    goal_away_probability: float
    home: TeamFeatures
    away: TeamFeatures

    def as_flat_dict(self) -> dict[str, Any]:
        values: dict[str, Any] = {
            "feature_contract_version": FEATURE_CONTRACT_VERSION,
            "match_uuid": self.match.match_uuid,
            "season": self.match.season,
            "feature_cutoff_at": self.feature_cutoff_at.isoformat(),
            "kickoff_at": self.match.kickoff_at.isoformat(),
            "prediction_lead_hours": self.prediction_lead_hours,
            "latest_input_available_after": (
                self.latest_input_available_after.isoformat()
                if self.latest_input_available_after is not None
                else None
            ),
            "available_result_count": self.available_result_count,
            "home_club_uuid": self.match.home_club_uuid,
            "home_club": self.match.home_club,
            "away_club_uuid": self.match.away_club_uuid,
            "away_club": self.match.away_club,
            "elo_home_probability": self.elo_home_probability,
            "elo_draw_probability": self.elo_draw_probability,
            "elo_away_probability": self.elo_away_probability,
            "goal_expected_home_goals": self.goal_expected_home_goals,
            "goal_expected_away_goals": self.goal_expected_away_goals,
            "goal_home_probability": self.goal_home_probability,
            "goal_draw_probability": self.goal_draw_probability,
            "goal_away_probability": self.goal_away_probability,
        }
        values.update({f"home_{key}": value for key, value in asdict(self.home).items()})
        values.update({f"away_{key}": value for key, value in asdict(self.away).items()})
        values.update(
            {
                "target_home_goals": self.match.home_goals,
                "target_away_goals": self.match.away_goals,
                "target_result": self.match.result,
            }
        )
        return values


@dataclass(frozen=True)
class PrematchFeatureDataset:
    rows: tuple[PrematchFeatureRow, ...]
    source_dataset_checksum: str
    seasons: tuple[str, ...]
    config: FeaturePipelineConfig


@dataclass(frozen=True)
class PendingResult:
    match: MatchRecord
    home_expected_points: float
    away_expected_points: float


def _points(match: MatchRecord, *, home: bool) -> int:
    if match.result == "D":
        return 1
    return 3 if (match.result == "H") == home else 0


def _mean(values: Sequence[float | int]) -> float | None:
    return sum(values) / len(values) if values else None


def _rate(observations: list[ResultObservation], predicate: str) -> float | None:
    if not observations:
        return None
    if predicate == "win":
        count = sum(item.points == 3 for item in observations)
    elif predicate == "draw":
        count = sum(item.points == 1 for item in observations)
    elif predicate == "loss":
        count = sum(item.points == 0 for item in observations)
    elif predicate == "clean_sheet":
        count = sum(item.goals_against == 0 for item in observations)
    else:
        count = sum(item.goals_for == 0 for item in observations)
    return count / len(observations)


def _team_features(
    *,
    club_uuid: str,
    venue: Literal["home", "away"],
    season: str,
    kickoff_at: datetime,
    cutoff: datetime,
    elo: EloModel,
    goals: DynamicGoalModel,
    results: dict[str, list[ResultObservation]],
    schedules: dict[str, list[ScheduleObservation]],
    previous_season_clubs: set[str] | None,
) -> TeamFeatures:
    history = results.get(club_uuid, [])
    last_3 = history[-3:]
    last_5 = history[-5:]
    last_10 = history[-10:]
    venue_history = [item for item in history if item.venue == venue][-5:]
    prior_schedule = [item for item in schedules.get(club_uuid, []) if item.kickoff_at < cutoff]
    season_fixtures = sum(item.season == season for item in prior_schedule)
    previous_kickoff = prior_schedule[-1].kickoff_at if prior_schedule else None
    rest_days = (
        (kickoff_at - previous_kickoff).total_seconds() / 86400
        if previous_kickoff is not None
        else None
    )
    points_recent = [item.points for item in last_5]
    latest_three = history[-3:]
    preceding_three = history[-6:-3]
    form_trend = None
    if len(latest_three) == 3 and len(preceding_three) == 3:
        form_trend = (
            sum(item.points for item in latest_three) / 3
            - sum(item.points for item in preceding_three) / 3
        )
    attack = goals.attack_snapshot().get(club_uuid, 0.0)
    defence = goals.defence_snapshot().get(club_uuid, 0.0)
    return TeamFeatures(
        elo_rating=elo.rating(club_uuid),
        goal_attack_strength=attack,
        goal_defence_strength=defence,
        history_match_count=len(history),
        season_fixture_count=season_fixtures,
        form_sample_count=len(last_10),
        points_last_3=sum(item.points for item in last_3),
        points_last_5=sum(item.points for item in last_5),
        points_last_10=sum(item.points for item in last_10),
        points_per_match_last_5=_mean(points_recent),
        goals_for_per_match_last_5=_mean([item.goals_for for item in last_5]),
        goals_against_per_match_last_5=_mean([item.goals_against for item in last_5]),
        goals_for_per_match_last_10=_mean([item.goals_for for item in last_10]),
        goals_against_per_match_last_10=_mean([item.goals_against for item in last_10]),
        goal_difference_per_match_last_5=_mean(
            [item.goals_for - item.goals_against for item in last_5]
        ),
        win_rate_last_5=_rate(last_5, "win"),
        draw_rate_last_5=_rate(last_5, "draw"),
        loss_rate_last_5=_rate(last_5, "loss"),
        clean_sheet_rate_last_5=_rate(last_5, "clean_sheet"),
        failed_to_score_rate_last_5=_rate(last_5, "failed_to_score"),
        venue_points_per_match_last_5=_mean([item.points for item in venue_history]),
        opponent_adjusted_points_last_5=_mean(
            [item.points - item.expected_points for item in last_5]
        ),
        form_trend=form_trend,
        rest_days=rest_days,
        matches_last_7_days=sum(
            item.kickoff_at >= kickoff_at - timedelta(days=7) for item in prior_schedule
        ),
        matches_last_14_days=sum(
            item.kickoff_at >= kickoff_at - timedelta(days=14) for item in prior_schedule
        ),
        matches_last_30_days=sum(
            item.kickoff_at >= kickoff_at - timedelta(days=30) for item in prior_schedule
        ),
        is_promoted=(
            int(club_uuid not in previous_season_clubs) if previous_season_clubs is not None else 0
        ),
        promotion_status_known=int(previous_season_clubs is not None),
        early_season=int(season_fixtures < 5),
        history_confidence=min(1.0, len(history) / 20),
        missing_form_last_5=int(len(history) < 5),
        missing_rest=int(rest_days is None),
    )


def build_prematch_features(
    dataset: HistoricalDataset,
    *,
    config: FeaturePipelineConfig | None = None,
) -> PrematchFeatureDataset:
    """Create one reproducible row per fixture using only its 24-hour snapshot."""

    selected = config or FeaturePipelineConfig()
    elo = EloModel(selected.elo)
    goals = DynamicGoalModel(selected.goals)
    result_history: dict[str, list[ResultObservation]] = {}
    schedule_history: dict[str, list[ScheduleObservation]] = {}
    pending: list[tuple[datetime, str, PendingResult]] = []
    rows: list[PrematchFeatureRow] = []
    current_season: str | None = None
    latest_available: datetime | None = None
    available_count = 0

    clubs_by_season: dict[str, set[str]] = {season: set() for season in dataset.seasons}
    for record in dataset.records:
        clubs_by_season[record.season].update((record.home_club_uuid, record.away_club_uuid))
    prior_clubs: dict[str, set[str] | None] = {}
    for index, season in enumerate(dataset.seasons):
        prior_clubs[season] = clubs_by_season[dataset.seasons[index - 1]] if index else None

    def apply_available(cutoff: datetime | None = None) -> None:
        nonlocal latest_available, available_count
        while pending and (cutoff is None or pending[0][0] < cutoff):
            _, _, completed = heapq.heappop(pending)
            match = completed.match
            result_history.setdefault(match.home_club_uuid, []).append(
                ResultObservation(
                    kickoff_at=match.kickoff_at,
                    available_after=match.available_after,
                    season=match.season,
                    venue="home",
                    points=_points(match, home=True),
                    goals_for=match.home_goals,
                    goals_against=match.away_goals,
                    expected_points=completed.home_expected_points,
                )
            )
            result_history.setdefault(match.away_club_uuid, []).append(
                ResultObservation(
                    kickoff_at=match.kickoff_at,
                    available_after=match.available_after,
                    season=match.season,
                    venue="away",
                    points=_points(match, home=False),
                    goals_for=match.away_goals,
                    goals_against=match.home_goals,
                    expected_points=completed.away_expected_points,
                )
            )
            result_history[match.home_club_uuid].sort(key=lambda item: item.kickoff_at)
            result_history[match.away_club_uuid].sort(key=lambda item: item.kickoff_at)
            elo.update(match)
            goals.update(match)
            latest_available = (
                match.available_after
                if latest_available is None
                else max(latest_available, match.available_after)
            )
            available_count += 1

    for match in dataset.records:
        cutoff = match.kickoff_at - selected.prediction_lead
        apply_available(cutoff)
        if match.season != current_season:
            elo.begin_season(match.season)
            goals.begin_season(match.season)
            current_season = match.season

        elo_probabilities = elo.predict(match.home_club_uuid, match.away_club_uuid)
        goal_forecast = goals.predict(match.home_club_uuid, match.away_club_uuid)
        home_features = _team_features(
            club_uuid=match.home_club_uuid,
            venue="home",
            season=match.season,
            kickoff_at=match.kickoff_at,
            cutoff=cutoff,
            elo=elo,
            goals=goals,
            results=result_history,
            schedules=schedule_history,
            previous_season_clubs=prior_clubs[match.season],
        )
        away_features = _team_features(
            club_uuid=match.away_club_uuid,
            venue="away",
            season=match.season,
            kickoff_at=match.kickoff_at,
            cutoff=cutoff,
            elo=elo,
            goals=goals,
            results=result_history,
            schedules=schedule_history,
            previous_season_clubs=prior_clubs[match.season],
        )
        rows.append(
            PrematchFeatureRow(
                match=match,
                feature_cutoff_at=cutoff,
                latest_input_available_after=latest_available,
                available_result_count=available_count,
                prediction_lead_hours=selected.prediction_lead.total_seconds() / 3600,
                elo_home_probability=elo_probabilities.home,
                elo_draw_probability=elo_probabilities.draw,
                elo_away_probability=elo_probabilities.away,
                goal_expected_home_goals=goal_forecast.expected_home_goals,
                goal_expected_away_goals=goal_forecast.expected_away_goals,
                goal_home_probability=goal_forecast.outcome_probabilities.home,
                goal_draw_probability=goal_forecast.outcome_probabilities.draw,
                goal_away_probability=goal_forecast.outcome_probabilities.away,
                home=home_features,
                away=away_features,
            )
        )
        schedule_history.setdefault(match.home_club_uuid, []).append(
            ScheduleObservation(match.kickoff_at, match.season, "home")
        )
        schedule_history.setdefault(match.away_club_uuid, []).append(
            ScheduleObservation(match.kickoff_at, match.season, "away")
        )
        heapq.heappush(
            pending,
            (
                match.available_after,
                match.match_uuid,
                PendingResult(
                    match=match,
                    home_expected_points=(3 * elo_probabilities.home + elo_probabilities.draw),
                    away_expected_points=(3 * elo_probabilities.away + elo_probabilities.draw),
                ),
            ),
        )
    return PrematchFeatureDataset(
        rows=tuple(rows),
        source_dataset_checksum=dataset.checksum,
        seasons=dataset.seasons,
        config=selected,
    )
