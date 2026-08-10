"""Export canonical player observations into the Phase 10 CSV contracts."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.models import (
    Match,
    PlayerAvailabilityReport,
    PlayerMatchPerformance,
    Season,
    TransferObservation,
)

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


@dataclass(frozen=True)
class ExportedPlayerContext:
    performance_path: Path
    performance_count: int
    performance_checksum: str
    availability_path: Path
    availability_count: int
    availability_checksum: str
    transfer_path: Path
    transfer_count: int
    transfer_checksum: str


def _csv_bytes(columns: tuple[str, ...], rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _write(path: Path, body: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def _normalized_position(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in ("g", "gk", "goalkeeper", "keeper"):
        return "goalkeeper"
    if normalized in ("d", "defender") or "back" in normalized:
        return "defender"
    if normalized in ("m", "midfielder") or "midfield" in normalized:
        return "midfielder"
    if normalized in ("a", "f", "attacker", "forward", "striker", "winger"):
        return "attacker"
    raise ValueError(f"unsupported player position for modeling export: {value!r}")


async def export_player_context(
    session: AsyncSession,
    *,
    output_root: Path,
) -> ExportedPlayerContext:
    performance_result = await session.execute(
        select(PlayerMatchPerformance, Match, Season)
        .join(Match, Match.match_uuid == PlayerMatchPerformance.match_uuid)
        .join(Season, Season.season_uuid == Match.season_uuid)
        .order_by(
            Match.current_kickoff_at,
            PlayerMatchPerformance.club_uuid,
            PlayerMatchPerformance.player_uuid,
        )
    )
    performance_rows: list[dict[str, Any]] = []
    for performance, match, season in performance_result.all():
        if performance.club_uuid == match.home_club_uuid:
            opponent_uuid = match.away_club_uuid
        elif performance.club_uuid == match.away_club_uuid:
            opponent_uuid = match.home_club_uuid
        else:
            raise ValueError("player performance club does not belong to its match")
        statistics = performance.statistics or {}
        performance_rows.append(
            {
                "match_uuid": str(match.match_uuid),
                "season": season.label,
                "kickoff_at": match.current_kickoff_at.isoformat(),
                "available_after": performance.available_after.isoformat(),
                "club_uuid": str(performance.club_uuid),
                "opponent_club_uuid": str(opponent_uuid),
                "player_uuid": str(performance.player_uuid),
                "position": _normalized_position(performance.position),
                "started": int(performance.started),
                "minutes": performance.minutes if performance.minutes is not None else 0,
                "rating": float(performance.rating) if performance.rating is not None else "",
                "goals": int(statistics.get("goals", 0) or 0),
                "assists": int(statistics.get("assists", 0) or 0),
            }
        )

    availability_records = list(
        await session.scalars(
            select(PlayerAvailabilityReport)
            .where(PlayerAvailabilityReport.match_uuid.is_not(None))
            .order_by(
                PlayerAvailabilityReport.observed_at,
                PlayerAvailabilityReport.match_uuid,
                PlayerAvailabilityReport.player_uuid,
            )
        )
    )
    availability_rows = [
        {
            "target_match_uuid": str(record.match_uuid),
            "club_uuid": str(record.club_uuid),
            "player_uuid": str(record.player_uuid),
            "observed_at": record.observed_at.isoformat(),
            "status": record.status.value,
            "availability_probability": float(record.availability_probability),
        }
        for record in availability_records
    ]

    transfer_records = list(
        await session.scalars(
            select(TransferObservation).order_by(
                TransferObservation.observed_at,
                TransferObservation.transfer_date,
                TransferObservation.player_uuid,
            )
        )
    )
    transfer_rows = [
        {
            "player_uuid": str(record.player_uuid),
            "from_club_uuid": (
                str(record.from_club_uuid) if record.from_club_uuid is not None else ""
            ),
            "to_club_uuid": (str(record.to_club_uuid) if record.to_club_uuid is not None else ""),
            "transfer_date": record.transfer_date.isoformat(),
            "observed_at": record.observed_at.isoformat(),
        }
        for record in transfer_records
    ]

    performance_path = output_root / "player_performances.csv"
    availability_path = output_root / "availability_observations.csv"
    transfer_path = output_root / "transfer_observations.csv"
    performance_body = _csv_bytes(PERFORMANCE_COLUMNS, performance_rows)
    availability_body = _csv_bytes(AVAILABILITY_COLUMNS, availability_rows)
    transfer_body = _csv_bytes(TRANSFER_COLUMNS, transfer_rows)
    return ExportedPlayerContext(
        performance_path=performance_path,
        performance_count=len(performance_rows),
        performance_checksum=_write(performance_path, performance_body),
        availability_path=availability_path,
        availability_count=len(availability_rows),
        availability_checksum=_write(availability_path, availability_body),
        transfer_path=transfer_path,
        transfer_count=len(transfer_rows),
        transfer_checksum=_write(transfer_path, transfer_body),
    )
