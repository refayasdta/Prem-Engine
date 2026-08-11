"""Deterministic Premier League standings calculation from canonical scores."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

STANDINGS_CALCULATION_VERSION = "premier-league-v1-points-gd-gf"


@dataclass(frozen=True)
class MatchScore:
    match_uuid: UUID
    home_club_uuid: UUID
    away_club_uuid: UUID
    home_goals: int
    away_goals: int


@dataclass(frozen=True)
class CalculatedStandingsRow:
    position: int
    club_uuid: UUID
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int


@dataclass
class _Accumulator:
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0


def calculate_standings(
    club_names: Mapping[UUID, str], scores: Iterable[MatchScore]
) -> tuple[CalculatedStandingsRow, ...]:
    """Apply points, goal difference, and goals scored with a stable name fallback."""

    totals = {club_uuid: _Accumulator() for club_uuid in club_names}
    for score in scores:
        home = totals.setdefault(score.home_club_uuid, _Accumulator())
        away = totals.setdefault(score.away_club_uuid, _Accumulator())
        home.played += 1
        away.played += 1
        home.goals_for += score.home_goals
        home.goals_against += score.away_goals
        away.goals_for += score.away_goals
        away.goals_against += score.home_goals
        if score.home_goals > score.away_goals:
            home.won += 1
            home.points += 3
            away.lost += 1
        elif score.home_goals < score.away_goals:
            away.won += 1
            away.points += 3
            home.lost += 1
        else:
            home.drawn += 1
            away.drawn += 1
            home.points += 1
            away.points += 1

    ordered = sorted(
        totals.items(),
        key=lambda item: (
            -item[1].points,
            -(item[1].goals_for - item[1].goals_against),
            -item[1].goals_for,
            club_names.get(item[0], str(item[0])).casefold(),
        ),
    )
    return tuple(
        CalculatedStandingsRow(
            position=position,
            club_uuid=club_uuid,
            played=total.played,
            won=total.won,
            drawn=total.drawn,
            lost=total.lost,
            goals_for=total.goals_for,
            goals_against=total.goals_against,
            goal_difference=total.goals_for - total.goals_against,
            points=total.points,
        )
        for position, (club_uuid, total) in enumerate(ordered, 1)
    )
