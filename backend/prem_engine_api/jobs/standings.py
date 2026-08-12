"""Persist simulated standings snapshots for background recalculation jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.enums import PredictionState, StandingsKind
from prem_engine_api.domain.models import (
    Club,
    Match,
    PredictionVersion,
    SeasonClub,
    StandingsRow,
    StandingsSnapshot,
    StoredSimulation,
)
from prem_engine_api.domain.standings import (
    STANDINGS_CALCULATION_VERSION,
    MatchScore,
    calculate_standings,
)


class StandingsRecalculationError(RuntimeError):
    """Raised when a standings job no longer points to a canonical match."""


@dataclass(frozen=True)
class StandingsRecalculation:
    snapshot_uuid: UUID
    season_uuid: UUID
    source_fixture_count: int
    row_count: int


async def recalculate_simulated_standings(
    session: AsyncSession, *, match_uuid: UUID, as_of: datetime
) -> StandingsRecalculation:
    """Append one leakage-safe simulated table for the match's season."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("standings calculation time must include a timezone")
    trigger_match = await session.get(Match, match_uuid)
    if trigger_match is None:
        raise StandingsRecalculationError("standings job match no longer exists")

    season_uuid = trigger_match.season_uuid
    season_matches = list(
        await session.scalars(select(Match).where(Match.season_uuid == season_uuid))
    )
    club_ids = set(
        await session.scalars(
            select(SeasonClub.club_uuid).where(SeasonClub.season_uuid == season_uuid)
        )
    )
    for match in season_matches:
        club_ids.update((match.home_club_uuid, match.away_club_uuid))
    clubs = (
        list(await session.scalars(select(Club).where(Club.club_uuid.in_(club_ids))))
        if club_ids
        else []
    )
    club_names = {club.club_uuid: club.canonical_name for club in clubs}

    records = (
        await session.execute(
            select(Match, StoredSimulation)
            .join(PredictionVersion, PredictionVersion.match_uuid == Match.match_uuid)
            .join(
                StoredSimulation,
                StoredSimulation.prediction_version_uuid
                == PredictionVersion.prediction_version_uuid,
            )
            .where(
                Match.season_uuid == season_uuid,
                PredictionVersion.state.in_(
                    (PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)
                ),
            )
        )
    ).all()
    scores = tuple(
        MatchScore(
            match_uuid=match.match_uuid,
            home_club_uuid=match.home_club_uuid,
            away_club_uuid=match.away_club_uuid,
            home_goals=simulation.home_goals,
            away_goals=simulation.away_goals,
        )
        for match, simulation in records
        if as_of
        >= simulation.presentation_started_at
        + timedelta(seconds=simulation.presentation_duration_seconds)
    )
    calculated = calculate_standings(club_names, scores)
    snapshot = StandingsSnapshot(
        season_uuid=season_uuid,
        kind=StandingsKind.SIMULATED,
        as_of=as_of,
        calculation_version=STANDINGS_CALCULATION_VERSION,
        source_fixture_count=len(scores),
    )
    session.add(snapshot)
    await session.flush()
    session.add_all(
        StandingsRow(
            snapshot_uuid=snapshot.snapshot_uuid,
            club_uuid=row.club_uuid,
            position=row.position,
            played=row.played,
            won=row.won,
            drawn=row.drawn,
            lost=row.lost,
            goals_for=row.goals_for,
            goals_against=row.goals_against,
            goal_difference=row.goal_difference,
            points=row.points,
        )
        for row in calculated
    )
    await session.flush()
    return StandingsRecalculation(
        snapshot_uuid=snapshot.snapshot_uuid,
        season_uuid=season_uuid,
        source_fixture_count=len(scores),
        row_count=len(calculated),
    )
