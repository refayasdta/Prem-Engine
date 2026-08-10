"""Leakage-safe expected lineups built from canonical player observations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.models import (
    Match,
    Player,
    PlayerAvailabilityReport,
    PlayerMatchPerformance,
    SquadMembership,
    TransferObservation,
)
from prem_engine_api.forecasting.contracts import LineupPlayer, PlayerPosition, TeamLineup

RECENT_SQUAD_WINDOW = timedelta(days=400)
FORMATION_REQUIREMENTS: dict[PlayerPosition, int] = {
    "GK": 1,
    "DEF": 4,
    "MID": 3,
    "FWD": 3,
}
UNKNOWN_AVAILABILITY = 0.75


class LineupCoverageError(RuntimeError):
    """Raised instead of inventing players when current squad coverage is inadequate."""


@dataclass(frozen=True)
class _Candidate:
    player_uuid: UUID
    name: str
    position: PlayerPosition
    shirt_number: int | None
    starting_probability: float
    availability_probability: float
    strength: float
    evidence: float

    @property
    def selection_score(self) -> float:
        return (
            self.starting_probability
            * self.availability_probability
            * (1.0 + max(-0.5, self.strength))
        )


def _position(value: str | None) -> PlayerPosition | None:
    normalized = (value or "").strip().casefold()
    if normalized in {"g", "gk", "gkp", "goalkeeper", "keeper"}:
        return "GK"
    if normalized in {"d", "def", "defender"} or "back" in normalized:
        return "DEF"
    if normalized in {"m", "mid", "midfielder"} or "midfield" in normalized:
        return "MID"
    if normalized in {"a", "f", "fwd", "attacker", "forward", "striker", "winger"}:
        return "FWD"
    return None


def _profile(
    player: Player,
    history: list[PlayerMatchPerformance],
    *,
    membership: SquadMembership | None,
    availability_probability: float,
) -> _Candidate | None:
    recent = history[-10:]
    position = _position(recent[-1].position if recent else None) or _position(
        membership.primary_position if membership is not None else None
    )
    if position is None:
        return None
    weights = [0.85 ** (len(recent) - index - 1) for index in range(len(recent))]
    if recent:
        start_signals = [
            (
                (
                    float(item.started)
                    if item.started is not None
                    else min(1.0, (item.minutes or 0) / 90)
                ),
                weight,
            )
            for item, weight in zip(recent, weights, strict=True)
        ]
        total_weight = sum(weight for _, weight in start_signals)
        starting_probability = (
            sum(signal * weight for signal, weight in start_signals) / total_weight
        )
        minutes = sum(item.minutes or 0 for item in recent)
        rating_values = [
            (float(item.rating), weight)
            for item, weight in zip(recent, weights, strict=True)
            if item.rating is not None
        ]
        rating = (
            sum(value * weight for value, weight in rating_values)
            / sum(weight for _, weight in rating_values)
            if rating_values
            else 6.5
        )
        goals = sum(float((item.statistics or {}).get("goals", 0) or 0) for item in recent)
        assists = sum(float((item.statistics or {}).get("assists", 0) or 0) for item in recent)
        strength = (rating - 6.5) / 1.5 + 0.35 * 90 * goals / max(90, minutes)
        strength += 0.25 * 90 * assists / max(90, minutes)
        evidence = min(1.0, minutes / 900)
    else:
        starting_probability = 0.05
        strength = -0.25
        evidence = 0.1
    return _Candidate(
        player_uuid=player.player_uuid,
        name=player.canonical_name,
        position=position,
        shirt_number=membership.shirt_number if membership is not None else None,
        starting_probability=max(0.0, min(1.0, starting_probability)),
        availability_probability=max(0.0, min(1.0, availability_probability)),
        strength=strength,
        evidence=evidence,
    )


def _recent_formation_requirements(
    performance_rows: list[Any],
) -> tuple[dict[PlayerPosition, int], str, float]:
    """Infer the expected position-group shape from up to five observed starting XIs."""

    by_match: dict[UUID, list[PlayerMatchPerformance]] = {}
    match_order: dict[UUID, datetime] = {}
    for performance, match, _ in performance_rows:
        if performance.started is True:
            by_match.setdefault(match.match_uuid, []).append(performance)
            match_order[match.match_uuid] = match.current_kickoff_at
    shapes: list[tuple[datetime, int, int, int]] = []
    for match_uuid, starters in by_match.items():
        positions = [_position(item.position) for item in starters]
        if len(starters) != 11 or positions.count("GK") != 1:
            continue
        defenders = positions.count("DEF")
        midfielders = positions.count("MID")
        forwards = positions.count("FWD")
        if defenders + midfielders + forwards != 10:
            continue
        shapes.append((match_order[match_uuid], defenders, midfielders, forwards))
    recent = sorted(shapes)[-5:]
    if not recent:
        return FORMATION_REQUIREMENTS.copy(), "4-3-3", 0.0
    labels = [(defenders, midfielders, forwards) for _, defenders, midfielders, forwards in recent]
    counts = Counter(labels)
    selected = max(enumerate(labels), key=lambda indexed: (counts[indexed[1]], indexed[0]))[1]
    defenders, midfielders, forwards = selected
    return (
        {"GK": 1, "DEF": defenders, "MID": midfielders, "FWD": forwards},
        f"{defenders}-{midfielders}-{forwards}",
        len(recent) / 5,
    )


def _select(
    candidates: list[_Candidate], requirements: dict[PlayerPosition, int]
) -> tuple[list[_Candidate], list[_Candidate]]:
    starters: list[_Candidate] = []
    for position, count in requirements.items():
        positioned = sorted(
            (item for item in candidates if item.position == position),
            key=lambda item: (item.selection_score, item.evidence, str(item.player_uuid)),
            reverse=True,
        )
        if position == "GK" and not positioned:
            raise LineupCoverageError("expected lineup has no identified goalkeeper")
        starters.extend(positioned[:count])
    selected = {item.player_uuid for item in starters}
    remaining = sorted(
        (item for item in candidates if item.player_uuid not in selected),
        key=lambda item: (item.selection_score, item.evidence, str(item.player_uuid)),
        reverse=True,
    )
    starters.extend(remaining[: max(0, 11 - len(starters))])
    if len(starters) != 11:
        raise LineupCoverageError("expected lineup has fewer than 11 eligible players")
    selected = {item.player_uuid for item in starters}
    substitutes = sorted(
        (item for item in candidates if item.player_uuid not in selected),
        key=lambda item: (item.selection_score, item.evidence, str(item.player_uuid)),
        reverse=True,
    )[:7]
    if len(substitutes) < 3:
        raise LineupCoverageError("expected lineup has fewer than three eligible substitutes")
    return starters, substitutes


def _to_contract(
    candidates: list[_Candidate], *, used_numbers: set[int]
) -> tuple[LineupPlayer, ...]:
    output: list[LineupPlayer] = []
    next_slot = 1
    for item in candidates:
        number = item.shirt_number
        source = "observed"
        if number is None or not 1 <= number <= 99 or number in used_numbers:
            while next_slot in used_numbers:
                next_slot += 1
            number = next_slot
            source = "presentation_slot"
        used_numbers.add(number)
        output.append(
            LineupPlayer(
                player_uuid=item.player_uuid,
                name=item.name,
                position=item.position,
                shirt_number=number,
                shirt_number_source=source,  # type: ignore[arg-type]
                starting_probability=item.starting_probability,
                availability_probability=item.availability_probability,
            )
        )
    return tuple(output)


async def expected_lineup_for_club(
    session: AsyncSession,
    *,
    match_uuid: UUID,
    season_uuid: UUID,
    club_uuid: UUID,
    club_name: str,
    short_name: str,
    kickoff_at: datetime,
    cutoff: datetime,
) -> tuple[TeamLineup, datetime | None]:
    """Use only observations available before cutoff and never create fake players."""

    performance_rows = list(
        (
            await session.execute(
                select(PlayerMatchPerformance, Match, Player)
                .join(Match, Match.match_uuid == PlayerMatchPerformance.match_uuid)
                .join(Player, Player.player_uuid == PlayerMatchPerformance.player_uuid)
                .where(
                    PlayerMatchPerformance.club_uuid == club_uuid,
                    PlayerMatchPerformance.available_after < cutoff,
                    Match.current_kickoff_at >= kickoff_at - RECENT_SQUAD_WINDOW,
                    Match.current_kickoff_at < kickoff_at,
                )
                .order_by(
                    PlayerMatchPerformance.available_after,
                    PlayerMatchPerformance.player_uuid,
                )
            )
        ).all()
    )
    histories: dict[UUID, list[PlayerMatchPerformance]] = {}
    players: dict[UUID, Player] = {}
    latest_used: datetime | None = None
    for performance, _, player in performance_rows:
        histories.setdefault(player.player_uuid, []).append(performance)
        players[player.player_uuid] = player
        latest_used = (
            performance.available_after
            if latest_used is None
            else max(latest_used, performance.available_after)
        )

    membership_rows = (
        await session.execute(
            select(SquadMembership, Player)
            .join(Player, Player.player_uuid == SquadMembership.player_uuid)
            .where(
                SquadMembership.season_uuid == season_uuid,
                SquadMembership.club_uuid == club_uuid,
                SquadMembership.joined_on <= kickoff_at.date(),
                or_(
                    SquadMembership.left_on.is_(None),
                    SquadMembership.left_on >= kickoff_at.date(),
                ),
            )
        )
    ).all()
    memberships: dict[UUID, SquadMembership] = {}
    for membership, player in membership_rows:
        memberships[player.player_uuid] = membership
        players[player.player_uuid] = player

    transfers = list(
        await session.scalars(
            select(TransferObservation)
            .where(
                TransferObservation.observed_at < cutoff,
                TransferObservation.transfer_date <= cutoff.date(),
                or_(
                    TransferObservation.from_club_uuid == club_uuid,
                    TransferObservation.to_club_uuid == club_uuid,
                ),
            )
            .order_by(TransferObservation.observed_at)
        )
    )
    latest_transfer: dict[UUID, TransferObservation] = {}
    for transfer in transfers:
        latest_transfer[transfer.player_uuid] = transfer
        latest_used = (
            transfer.observed_at if latest_used is None else max(latest_used, transfer.observed_at)
        )
    for player_uuid, transfer in latest_transfer.items():
        if transfer.from_club_uuid == club_uuid and transfer.to_club_uuid != club_uuid:
            players.pop(player_uuid, None)
            histories.pop(player_uuid, None)
            memberships.pop(player_uuid, None)

    availability_rows = list(
        await session.scalars(
            select(PlayerAvailabilityReport)
            .where(
                PlayerAvailabilityReport.club_uuid == club_uuid,
                PlayerAvailabilityReport.observed_at < cutoff,
                or_(
                    PlayerAvailabilityReport.match_uuid == match_uuid,
                    PlayerAvailabilityReport.match_uuid.is_(None),
                ),
            )
            .order_by(PlayerAvailabilityReport.observed_at)
        )
    )
    availability: dict[UUID, PlayerAvailabilityReport] = {}
    for item in availability_rows:
        availability[item.player_uuid] = item
        latest_used = (
            item.observed_at if latest_used is None else max(latest_used, item.observed_at)
        )

    candidates: list[_Candidate] = []
    for player_uuid, player in players.items():
        report = availability.get(player_uuid)
        profile = _profile(
            player,
            histories.get(player_uuid, []),
            membership=memberships.get(player_uuid),
            availability_probability=(
                float(report.availability_probability)
                if report is not None
                else UNKNOWN_AVAILABILITY
            ),
        )
        if profile is not None and profile.availability_probability > 0.0:
            candidates.append(profile)
    requirements, formation, formation_confidence = _recent_formation_requirements(performance_rows)
    starters, substitutes = _select(candidates, requirements)
    used_numbers: set[int] = set()
    confidence = sum(item.evidence for item in starters) / 11
    confidence *= sum(item.availability_probability for item in starters) / 11
    confidence *= 0.7 + 0.3 * formation_confidence
    return (
        TeamLineup(
            club_uuid=club_uuid,
            club_name=club_name,
            short_name=short_name,
            formation=formation,
            starters=_to_contract(starters, used_numbers=used_numbers),
            substitutes=_to_contract(substitutes, used_numbers=used_numbers),
            confidence=max(0.0, min(1.0, confidence)),
        ),
        latest_used,
    )
