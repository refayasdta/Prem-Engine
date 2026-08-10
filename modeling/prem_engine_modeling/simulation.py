"""Deterministic, internally consistent Phase 13 quick-match simulation."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

TeamSide = Literal["home", "away"]
EventType = Literal[
    "kickoff",
    "shot",
    "shot_on_target",
    "goal",
    "corner",
    "foul",
    "yellow_card",
    "red_card",
    "substitution",
    "half_time",
    "second_half",
    "full_time",
]

SIMULATION_SCHEMA_VERSION = "stored-simulation-v1"


@dataclass(frozen=True)
class SimulationPlayer:
    player_uuid: str
    name: str
    position: Literal["GK", "DEF", "MID", "FWD"]
    shirt_number: int


@dataclass(frozen=True)
class SimulationLineup:
    club_uuid: str
    club_name: str
    short_name: str
    formation: str
    starters: tuple[SimulationPlayer, ...]
    substitutes: tuple[SimulationPlayer, ...]

    def __post_init__(self) -> None:
        if len(self.starters) != 11 or len(self.substitutes) < 3:
            raise ValueError("simulation lineups require 11 starters and at least 3 substitutes")
        identifiers = [player.player_uuid for player in self.starters + self.substitutes]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("simulation lineup player UUIDs must be unique")


@dataclass(frozen=True)
class SimulationForecast:
    match_uuid: str
    prediction_version_uuid: str
    feature_cutoff_at: str
    locked_at: str
    outcome_model_version: str
    statistics_model_version: str
    expected_home_goals: float
    expected_away_goals: float
    score_matrix: tuple[tuple[float, ...], ...]
    statistic_means: dict[str, float]
    home_lineup: SimulationLineup
    away_lineup: SimulationLineup


@dataclass(frozen=True)
class SimulationEvent:
    event_id: str
    minute: int
    second: int
    event_type: EventType
    team: TeamSide | None
    player_uuid: str | None
    player_name: str | None
    secondary_player_uuid: str | None
    secondary_player_name: str | None
    commentary: str
    home_score: int
    away_score: int


@dataclass(frozen=True)
class StoredSimulationPayload:
    schema_version: str
    simulation_uuid: str
    match_uuid: str
    prediction_version_uuid: str
    random_seed: int
    feature_cutoff_at: str
    locked_at: str
    outcome_model_version: str
    statistics_model_version: str
    expected_home_goals: float
    expected_away_goals: float
    home_win_probability: float
    draw_probability: float
    away_win_probability: float
    home_team: dict[str, Any]
    away_team: dict[str, Any]
    home_goals: int
    away_goals: int
    statistics: dict[str, int]
    events: tuple[SimulationEvent, ...]
    checksum: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _PendingEvent:
    minute: int
    second: int
    event_type: EventType
    team: TeamSide | None
    player: SimulationPlayer | None
    secondary: SimulationPlayer | None
    commentary: str


def _sample_poisson(rng: random.Random, mean: float) -> int:
    if not math.isfinite(mean) or mean < 0.0:
        raise ValueError("statistic means must be finite and non-negative")
    if mean == 0.0:
        return 0
    threshold = math.exp(-mean)
    product_value = 1.0
    count = 0
    while product_value > threshold:
        count += 1
        product_value *= rng.random()
    return count - 1


def _sample_scoreline(rng: random.Random, matrix: tuple[tuple[float, ...], ...]) -> tuple[int, int]:
    if not matrix or any(len(row) != len(matrix[0]) for row in matrix):
        raise ValueError("score matrix must be non-empty and rectangular")
    values = [value for row in matrix for value in row]
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError("score matrix contains invalid probabilities")
    total = sum(values)
    if not math.isclose(total, 1.0, abs_tol=1e-8):
        raise ValueError("score matrix probabilities must sum to one")
    choice = rng.random()
    cumulative = 0.0
    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            cumulative += probability
            if choice <= cumulative:
                return home_goals, away_goals
    return len(matrix) - 1, len(matrix[-1]) - 1


def _sample_minute(rng: random.Random, *, first_half: bool | None = None) -> tuple[int, int]:
    if first_half is True:
        return rng.randint(3, 44), rng.randint(0, 59)
    if first_half is False:
        return rng.randint(47, 89), rng.randint(0, 59)
    minute = rng.choice(tuple(range(3, 45)) + tuple(range(47, 90)))
    return minute, rng.randint(0, 59)


def _event_player(
    rng: random.Random,
    lineup: SimulationLineup,
    event_type: EventType,
) -> SimulationPlayer:
    if event_type in ("goal", "shot", "shot_on_target", "corner"):
        candidates = tuple(
            player for player in lineup.starters if player.position in ("MID", "FWD")
        )
    elif event_type in ("foul", "yellow_card", "red_card"):
        candidates = tuple(
            player for player in lineup.starters if player.position in ("DEF", "MID")
        )
    else:
        candidates = lineup.starters
    return rng.choice(candidates or lineup.starters)


def _commentary(
    event_type: EventType,
    lineup: SimulationLineup,
    player: SimulationPlayer | None,
    secondary: SimulationPlayer | None = None,
) -> str:
    name = player.name if player else lineup.short_name
    messages = {
        "goal": f"GOAL! {name} finishes the move for {lineup.short_name}.",
        "shot_on_target": f"{name} tests the goalkeeper with a firm effort.",
        "shot": f"{name} takes aim, but the effort misses the target.",
        "corner": f"{lineup.short_name} force another corner.",
        "foul": f"{name} is penalised after a late challenge.",
        "yellow_card": f"Yellow card for {name}.",
        "red_card": f"Red card! {name} is dismissed.",
        "substitution": (
            f"{lineup.short_name} change: {secondary.name if secondary else 'substitute'} "
            f"replaces {name}."
        ),
    }
    return messages.get(event_type, f"{lineup.short_name} restart play.")


def _team_events(
    rng: random.Random,
    *,
    side: TeamSide,
    lineup: SimulationLineup,
    goals: int,
    statistics: dict[str, int],
) -> list[_PendingEvent]:
    shots = max(goals, statistics[f"{side}_shots"])
    shots_on_target = min(shots, max(goals, statistics[f"{side}_shots_on_target"]))
    statistics[f"{side}_shots"] = shots
    statistics[f"{side}_shots_on_target"] = shots_on_target
    first_half_goals = min(goals, statistics[f"{side}_half_time_goals"])
    statistics[f"{side}_half_time_goals"] = first_half_goals
    pending: list[_PendingEvent] = []
    first_half_goal_slots = set(rng.sample(range(goals), first_half_goals))
    for goal_index in range(goals):
        player = _event_player(rng, lineup, "goal")
        assist_candidates = tuple(item for item in lineup.starters if item != player)
        assist = rng.choice(assist_candidates) if rng.random() < 0.72 else None
        minute, second = _sample_minute(rng, first_half=goal_index in first_half_goal_slots)
        pending.append(
            _PendingEvent(
                minute,
                second,
                "goal",
                side,
                player,
                assist,
                _commentary("goal", lineup, player, assist),
            )
        )
    for _ in range(shots_on_target - goals):
        player = _event_player(rng, lineup, "shot_on_target")
        minute, second = _sample_minute(rng)
        pending.append(
            _PendingEvent(
                minute,
                second,
                "shot_on_target",
                side,
                player,
                None,
                _commentary("shot_on_target", lineup, player),
            )
        )
    for _ in range(shots - shots_on_target):
        player = _event_player(rng, lineup, "shot")
        minute, second = _sample_minute(rng)
        pending.append(
            _PendingEvent(
                minute,
                second,
                "shot",
                side,
                player,
                None,
                _commentary("shot", lineup, player),
            )
        )
    statistic_events: tuple[tuple[EventType, str], ...] = (
        ("corner", "corners"),
        ("foul", "fouls"),
        ("yellow_card", "yellow_cards"),
        ("red_card", "red_cards"),
    )
    for event_type, key in statistic_events:
        for _ in range(statistics[f"{side}_{key}"]):
            player = _event_player(rng, lineup, event_type)
            minute, second = _sample_minute(rng)
            pending.append(
                _PendingEvent(
                    minute,
                    second,
                    event_type,
                    side,
                    player,
                    None,
                    _commentary(event_type, lineup, player),
                )
            )
    substitute_count = min(3, len(lineup.substitutes))
    outgoing = rng.sample(list(lineup.starters[1:]), substitute_count)
    incoming = rng.sample(list(lineup.substitutes), substitute_count)
    for player, substitute, minute in zip(
        outgoing,
        incoming,
        sorted(rng.sample(range(58, 84), substitute_count)),
        strict=True,
    ):
        pending.append(
            _PendingEvent(
                minute,
                rng.randint(0, 59),
                "substitution",
                side,
                player,
                substitute,
                _commentary("substitution", lineup, player, substitute),
            )
        )
    return pending


def _sample_statistics(rng: random.Random, means: dict[str, float]) -> dict[str, int]:
    required = {
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
    }
    missing = required.difference(means)
    if missing:
        raise ValueError(f"simulation statistic means are incomplete: {sorted(missing)}")
    return {key: _sample_poisson(rng, means[key]) for key in sorted(required)}


def _finalize_events(pending: list[_PendingEvent]) -> tuple[SimulationEvent, ...]:
    pending.extend(
        [
            _PendingEvent(0, 0, "kickoff", None, None, None, "Kick-off."),
            _PendingEvent(45, 0, "half_time", None, None, None, "Half-time."),
            _PendingEvent(46, 0, "second_half", None, None, None, "The second half begins."),
            _PendingEvent(90, 0, "full_time", None, None, None, "Full-time."),
        ]
    )
    priority = {"kickoff": 0, "half_time": 0, "second_half": 0, "full_time": 9}
    ordered = sorted(
        pending,
        key=lambda item: (
            item.minute,
            item.second,
            priority.get(item.event_type, 4),
            item.team or "",
        ),
    )
    home_score = 0
    away_score = 0
    result: list[SimulationEvent] = []
    for index, item in enumerate(ordered, 1):
        if item.event_type == "goal":
            if item.team == "home":
                home_score += 1
            else:
                away_score += 1
        result.append(
            SimulationEvent(
                event_id=f"event-{index:03d}",
                minute=item.minute,
                second=item.second,
                event_type=item.event_type,
                team=item.team,
                player_uuid=item.player.player_uuid if item.player else None,
                player_name=item.player.name if item.player else None,
                secondary_player_uuid=(item.secondary.player_uuid if item.secondary else None),
                secondary_player_name=(item.secondary.name if item.secondary else None),
                commentary=item.commentary,
                home_score=home_score,
                away_score=away_score,
            )
        )
    return tuple(result)


def _checksum(payload: StoredSimulationPayload) -> str:
    body = asdict(replace(payload, checksum=""))
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def generate_stored_simulation(
    forecast: SimulationForecast,
    *,
    random_seed: int,
) -> StoredSimulationPayload:
    """Generate the entire simulation once; viewers only replay this payload."""

    rng = random.Random(random_seed)
    home_goals, away_goals = _sample_scoreline(rng, forecast.score_matrix)
    statistics = _sample_statistics(rng, forecast.statistic_means)
    pending = _team_events(
        rng,
        side="home",
        lineup=forecast.home_lineup,
        goals=home_goals,
        statistics=statistics,
    )
    pending.extend(
        _team_events(
            rng,
            side="away",
            lineup=forecast.away_lineup,
            goals=away_goals,
            statistics=statistics,
        )
    )
    events = _finalize_events(pending)
    home_win_probability = sum(
        probability
        for home_index, row in enumerate(forecast.score_matrix)
        for away_index, probability in enumerate(row)
        if home_index > away_index
    )
    draw_probability = sum(
        row[index] for index, row in enumerate(forecast.score_matrix) if index < len(row)
    )
    away_win_probability = max(0.0, 1.0 - home_win_probability - draw_probability)
    simulation_uuid = str(
        uuid5(
            NAMESPACE_URL,
            f"prem-engine-simulation:{forecast.prediction_version_uuid}:{random_seed}",
        )
    )
    payload = StoredSimulationPayload(
        schema_version=SIMULATION_SCHEMA_VERSION,
        simulation_uuid=simulation_uuid,
        match_uuid=forecast.match_uuid,
        prediction_version_uuid=forecast.prediction_version_uuid,
        random_seed=random_seed,
        feature_cutoff_at=forecast.feature_cutoff_at,
        locked_at=forecast.locked_at,
        outcome_model_version=forecast.outcome_model_version,
        statistics_model_version=forecast.statistics_model_version,
        expected_home_goals=forecast.expected_home_goals,
        expected_away_goals=forecast.expected_away_goals,
        home_win_probability=home_win_probability,
        draw_probability=draw_probability,
        away_win_probability=away_win_probability,
        home_team=asdict(forecast.home_lineup),
        away_team=asdict(forecast.away_lineup),
        home_goals=home_goals,
        away_goals=away_goals,
        statistics=statistics,
        events=events,
        checksum="",
    )
    return replace(payload, checksum=_checksum(payload))


def validate_simulation_consistency(payload: StoredSimulationPayload) -> None:
    """Reject payloads whose score, event counts, order, or checksum disagree."""

    if payload.checksum != _checksum(payload):
        raise ValueError("simulation checksum does not match its payload")
    chronological = tuple(
        sorted(payload.events, key=lambda item: (item.minute, item.second, item.event_id))
    )
    if chronological != payload.events:
        raise ValueError("simulation events are not chronological")
    if not payload.events or payload.events[0].event_type != "kickoff":
        raise ValueError("simulation must begin with kick-off")
    if payload.events[-1].event_type != "full_time":
        raise ValueError("simulation must end at full-time")
    rolling_home = 0
    rolling_away = 0
    for event in payload.events:
        if event.event_type == "goal":
            rolling_home += event.team == "home"
            rolling_away += event.team == "away"
        if (event.home_score, event.away_score) != (rolling_home, rolling_away):
            raise ValueError("simulation event scoreboard is inconsistent")
    home_goals = sum(
        event.event_type == "goal" and event.team == "home" for event in payload.events
    )
    away_goals = sum(
        event.event_type == "goal" and event.team == "away" for event in payload.events
    )
    if (home_goals, away_goals) != (payload.home_goals, payload.away_goals):
        raise ValueError("simulation score does not match goal events")
    for side in ("home", "away"):
        team_events = tuple(event for event in payload.events if event.team == side)
        counts = {
            "half_time_goals": sum(
                event.event_type == "goal" and event.minute < 45 for event in team_events
            ),
            "shots": sum(
                event.event_type in ("shot", "shot_on_target", "goal") for event in team_events
            ),
            "shots_on_target": sum(
                event.event_type in ("shot_on_target", "goal") for event in team_events
            ),
            "corners": sum(event.event_type == "corner" for event in team_events),
            "fouls": sum(event.event_type == "foul" for event in team_events),
            "yellow_cards": sum(event.event_type == "yellow_card" for event in team_events),
            "red_cards": sum(event.event_type == "red_card" for event in team_events),
        }
        for name, count in counts.items():
            if count != payload.statistics[f"{side}_{name}"]:
                raise ValueError(f"{side} {name} does not match its event count")
