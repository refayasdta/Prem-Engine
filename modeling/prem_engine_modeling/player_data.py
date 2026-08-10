"""Strict normalized inputs for Phase 10 player context."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal, cast

PlayerPosition = Literal["goalkeeper", "defender", "midfielder", "attacker"]
AvailabilityStatus = Literal["available", "doubtful", "out", "suspended", "unknown"]

PERFORMANCE_COLUMNS = (
    "match_uuid",
    "season",
    "kickoff_at",
    "available_after",
    "club_uuid",
    "opponent_club_uuid",
    "player_uuid",
    "position",
    "started",
    "starting_status_source",
    "minutes",
    "rating",
    "goals",
    "assists",
)
AVAILABILITY_COLUMNS = (
    "target_match_uuid",
    "club_uuid",
    "player_uuid",
    "observed_at",
    "status",
    "availability_probability",
)
TRANSFER_COLUMNS = (
    "player_uuid",
    "from_club_uuid",
    "to_club_uuid",
    "transfer_date",
    "observed_at",
)


class PlayerDataContractError(ValueError):
    """Raised when normalized player inputs are ambiguous or unsafe."""


@dataclass(frozen=True)
class PlayerPerformance:
    match_uuid: str
    season: str
    kickoff_at: datetime
    available_after: datetime
    club_uuid: str
    opponent_club_uuid: str
    player_uuid: str
    position: PlayerPosition
    started: bool | None
    starting_status_source: Literal["observed", "inferred", "unknown"]
    minutes: int
    rating: float | None
    goals: int
    assists: int


@dataclass(frozen=True)
class AvailabilityObservation:
    target_match_uuid: str
    club_uuid: str
    player_uuid: str
    observed_at: datetime
    status: AvailabilityStatus
    availability_probability: float


@dataclass(frozen=True)
class TransferObservation:
    player_uuid: str
    from_club_uuid: str | None
    to_club_uuid: str | None
    transfer_date: date
    observed_at: datetime


@dataclass(frozen=True)
class PlayerContextDataset:
    performances: tuple[PlayerPerformance, ...]
    availability: tuple[AvailabilityObservation, ...]
    transfers: tuple[TransferObservation, ...]
    checksum: str


def _aware(value: str, *, field: str, row_number: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise PlayerDataContractError(f"row {row_number}: invalid {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PlayerDataContractError(f"row {row_number}: {field} needs a timezone")
    return parsed


def _rows(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.exists():
        raise PlayerDataContractError(f"required player input does not exist: {path}")
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != columns:
            raise PlayerDataContractError(f"{path.name} columns do not match the Phase 10 contract")
        return list(reader)


def _optional_float(value: str, *, field: str, row_number: int) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError as error:
        raise PlayerDataContractError(f"row {row_number}: invalid {field}") from error


def _checksum(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_player_context(
    *,
    performances_path: Path,
    availability_path: Path,
    transfers_path: Path,
) -> PlayerContextDataset:
    """Load normalized inputs while preserving observation-time semantics."""

    performance_rows = _rows(performances_path, PERFORMANCE_COLUMNS)
    availability_rows = _rows(availability_path, AVAILABILITY_COLUMNS)
    transfer_rows = _rows(transfers_path, TRANSFER_COLUMNS)
    performances: list[PlayerPerformance] = []
    performance_keys: set[tuple[str, str, str]] = set()
    for row_number, row in enumerate(performance_rows, 2):
        performance_key = (row["match_uuid"], row["club_uuid"], row["player_uuid"])
        if not all(performance_key) or performance_key in performance_keys:
            raise PlayerDataContractError(
                f"row {row_number}: missing or duplicate match/club/player performance"
            )
        performance_keys.add(performance_key)
        try:
            position = cast(PlayerPosition, row["position"].strip().lower())
            if position not in ("goalkeeper", "defender", "midfielder", "attacker"):
                raise ValueError
            started_raw = row["started"].strip()
            started_value = int(started_raw) if started_raw else None
            minutes = int(row["minutes"])
            goals = int(row["goals"])
            assists = int(row["assists"])
        except ValueError as error:
            raise PlayerDataContractError(
                f"row {row_number}: invalid position, started flag, minutes, goals, or assists"
            ) from error
        rating = _optional_float(row["rating"], field="rating", row_number=row_number)
        kickoff = _aware(row["kickoff_at"], field="kickoff_at", row_number=row_number)
        available_after = _aware(
            row["available_after"], field="available_after", row_number=row_number
        )
        start_source = row["starting_status_source"].strip().lower()
        if started_value not in (None, 0, 1) or not 0 <= minutes <= 130:
            raise PlayerDataContractError(f"row {row_number}: invalid start flag or minutes")
        if start_source not in ("observed", "inferred", "unknown"):
            raise PlayerDataContractError(f"row {row_number}: invalid starting-status source")
        if (started_value is None) != (start_source == "unknown"):
            raise PlayerDataContractError(
                f"row {row_number}: unknown start status and source must agree"
            )
        if goals < 0 or assists < 0 or (rating is not None and not 0 <= rating <= 10):
            raise PlayerDataContractError(f"row {row_number}: invalid player statistics")
        if available_after < kickoff:
            raise PlayerDataContractError(
                f"row {row_number}: post-match performance predates kickoff"
            )
        performances.append(
            PlayerPerformance(
                match_uuid=row["match_uuid"],
                season=row["season"],
                kickoff_at=kickoff,
                available_after=available_after,
                club_uuid=row["club_uuid"],
                opponent_club_uuid=row["opponent_club_uuid"],
                player_uuid=row["player_uuid"],
                position=position,
                started=bool(started_value) if started_value is not None else None,
                starting_status_source=cast(
                    Literal["observed", "inferred", "unknown"], start_source
                ),
                minutes=minutes,
                rating=rating,
                goals=goals,
                assists=assists,
            )
        )

    availability: list[AvailabilityObservation] = []
    availability_keys: set[tuple[str, str, str, datetime]] = set()
    for row_number, row in enumerate(availability_rows, 2):
        observed_at = _aware(row["observed_at"], field="observed_at", row_number=row_number)
        availability_key = (
            row["target_match_uuid"],
            row["club_uuid"],
            row["player_uuid"],
            observed_at,
        )
        if not all(availability_key[:3]) or availability_key in availability_keys:
            raise PlayerDataContractError(
                f"row {row_number}: missing or duplicate availability observation"
            )
        availability_keys.add(availability_key)
        status = cast(AvailabilityStatus, row["status"].strip().lower())
        if status not in ("available", "doubtful", "out", "suspended", "unknown"):
            raise PlayerDataContractError(f"row {row_number}: invalid availability status")
        probability = _optional_float(
            row["availability_probability"],
            field="availability_probability",
            row_number=row_number,
        )
        if probability is None or not 0 <= probability <= 1:
            raise PlayerDataContractError(
                f"row {row_number}: availability probability must be between zero and one"
            )
        availability.append(
            AvailabilityObservation(
                target_match_uuid=row["target_match_uuid"],
                club_uuid=row["club_uuid"],
                player_uuid=row["player_uuid"],
                observed_at=observed_at,
                status=status,
                availability_probability=probability,
            )
        )

    transfers: list[TransferObservation] = []
    for row_number, row in enumerate(transfer_rows, 2):
        try:
            transfer_date = date.fromisoformat(row["transfer_date"])
        except ValueError as error:
            raise PlayerDataContractError(f"row {row_number}: invalid transfer_date") from error
        observed_at = _aware(row["observed_at"], field="observed_at", row_number=row_number)
        from_club = row["from_club_uuid"] or None
        to_club = row["to_club_uuid"] or None
        if not row["player_uuid"] or (from_club is None and to_club is None):
            raise PlayerDataContractError(
                f"row {row_number}: transfer needs a player and at least one club"
            )
        if from_club is not None and from_club == to_club:
            raise PlayerDataContractError(f"row {row_number}: transfer clubs must differ")
        transfers.append(
            TransferObservation(
                player_uuid=row["player_uuid"],
                from_club_uuid=from_club,
                to_club_uuid=to_club,
                transfer_date=transfer_date,
                observed_at=observed_at,
            )
        )

    performances.sort(key=lambda item: (item.available_after, item.match_uuid, item.player_uuid))
    availability.sort(key=lambda item: (item.observed_at, item.target_match_uuid, item.player_uuid))
    transfers.sort(key=lambda item: (item.observed_at, item.transfer_date, item.player_uuid))
    paths = (performances_path, availability_path, transfers_path)
    return PlayerContextDataset(
        performances=tuple(performances),
        availability=tuple(availability),
        transfers=tuple(transfers),
        checksum=_checksum(paths),
    )
