"""Strict, chronological modeling input contracts."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

MatchResult = Literal["H", "D", "A"]
RESULT_ORDER: tuple[MatchResult, ...] = ("H", "D", "A")

REQUIRED_COLUMNS = {
    "match_uuid",
    "season",
    "kickoff_at",
    "home_club_uuid",
    "home_club",
    "away_club_uuid",
    "away_club",
    "home_goals",
    "away_goals",
    "result",
    "available_after",
    "lagged_history_only",
}


class DatasetContractError(ValueError):
    """Raised when a modeling export could permit invalid or leaky training."""


@dataclass(frozen=True)
class MatchRecord:
    match_uuid: str
    season: str
    kickoff_at: datetime
    available_after: datetime
    home_club_uuid: str
    home_club: str
    away_club_uuid: str
    away_club: str
    home_goals: int
    away_goals: int
    result: MatchResult


@dataclass(frozen=True)
class HistoricalDataset:
    records: tuple[MatchRecord, ...]
    checksum: str
    seasons: tuple[str, ...]

    def through_season(self, final_season: str) -> HistoricalDataset:
        """Return a prefix ending at one season without exposing later records."""

        try:
            final_index = self.seasons.index(final_season)
        except ValueError as error:
            raise DatasetContractError(f"unknown season: {final_season}") from error
        allowed = set(self.seasons[: final_index + 1])
        records = tuple(record for record in self.records if record.season in allowed)
        return HistoricalDataset(
            records=records,
            checksum=self.checksum,
            seasons=self.seasons[: final_index + 1],
        )


@dataclass(frozen=True)
class ChronologicalSplit:
    history_seasons: tuple[str, ...]
    validation_season: str
    test_seasons: tuple[str, ...]


def _aware_datetime(value: str, *, field: str, row_number: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise DatasetContractError(f"row {row_number}: invalid {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DatasetContractError(f"row {row_number}: {field} must include a timezone")
    return parsed


def _nonnegative_integer(value: str, *, field: str, row_number: int) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise DatasetContractError(f"row {row_number}: invalid {field}") from error
    if parsed < 0:
        raise DatasetContractError(f"row {row_number}: {field} cannot be negative")
    return parsed


def _result_for(home_goals: int, away_goals: int) -> MatchResult:
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


def _required(row: dict[str, str | None], field: str, row_number: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise DatasetContractError(f"row {row_number}: {field} is required")
    return value


def _parse_record(row: dict[str, str | None], row_number: int) -> MatchRecord:
    match_uuid = _required(row, "match_uuid", row_number)
    home_uuid = _required(row, "home_club_uuid", row_number)
    away_uuid = _required(row, "away_club_uuid", row_number)
    for field, value in (
        ("match_uuid", match_uuid),
        ("home_club_uuid", home_uuid),
        ("away_club_uuid", away_uuid),
    ):
        try:
            UUID(value)
        except ValueError as error:
            raise DatasetContractError(f"row {row_number}: invalid {field}") from error
    if home_uuid == away_uuid:
        raise DatasetContractError(f"row {row_number}: a club cannot play itself")

    kickoff = _aware_datetime(
        _required(row, "kickoff_at", row_number), field="kickoff_at", row_number=row_number
    )
    available_after = _aware_datetime(
        _required(row, "available_after", row_number),
        field="available_after",
        row_number=row_number,
    )
    if available_after <= kickoff:
        raise DatasetContractError(f"row {row_number}: outcome must become available after kickoff")
    if _required(row, "lagged_history_only", row_number).casefold() != "true":
        raise DatasetContractError(f"row {row_number}: row is not approved for lagged history")

    home_goals = _nonnegative_integer(
        _required(row, "home_goals", row_number), field="home_goals", row_number=row_number
    )
    away_goals = _nonnegative_integer(
        _required(row, "away_goals", row_number), field="away_goals", row_number=row_number
    )
    result_value = _required(row, "result", row_number).upper()
    if result_value not in RESULT_ORDER:
        raise DatasetContractError(f"row {row_number}: result must be H, D, or A")
    result: MatchResult = result_value
    if result != _result_for(home_goals, away_goals):
        raise DatasetContractError(f"row {row_number}: result contradicts the score")

    return MatchRecord(
        match_uuid=match_uuid,
        season=_required(row, "season", row_number),
        kickoff_at=kickoff,
        available_after=available_after,
        home_club_uuid=home_uuid,
        home_club=_required(row, "home_club", row_number),
        away_club_uuid=away_uuid,
        away_club=_required(row, "away_club", row_number),
        home_goals=home_goals,
        away_goals=away_goals,
        result=result,
    )


def load_historical_dataset(path: Path) -> HistoricalDataset:
    """Load the Phase 5 export and reject ordering or provenance violations."""

    body = path.read_bytes()
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DatasetContractError("modeling export must be UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        raise DatasetContractError("modeling export has no header")
    headers = tuple(reader.fieldnames)
    missing = sorted(REQUIRED_COLUMNS.difference(headers))
    if missing:
        raise DatasetContractError(f"modeling export is missing: {', '.join(missing)}")
    if any("odds" in header.casefold() or header.startswith("B365") for header in headers):
        raise DatasetContractError("benchmark odds cannot enter the baseline training export")

    records = tuple(_parse_record(row, row_number) for row_number, row in enumerate(reader, 2))
    if not records:
        raise DatasetContractError("modeling export contains no matches")
    match_ids = [record.match_uuid for record in records]
    if len(match_ids) != len(set(match_ids)):
        raise DatasetContractError("modeling export contains duplicate match UUIDs")
    chronological = tuple(sorted(records, key=lambda item: (item.kickoff_at, item.match_uuid)))
    if records != chronological:
        raise DatasetContractError("modeling export must be chronologically ordered")

    seasons: list[str] = []
    closed_seasons: set[str] = set()
    for record in records:
        if not seasons or seasons[-1] != record.season:
            if record.season in closed_seasons:
                raise DatasetContractError("season rows must form one chronological block")
            if seasons:
                closed_seasons.add(seasons[-1])
            seasons.append(record.season)
    return HistoricalDataset(
        records=records,
        checksum=hashlib.sha256(body).hexdigest(),
        seasons=tuple(seasons),
    )


def standard_six_season_split(dataset: HistoricalDataset) -> ChronologicalSplit:
    """Reserve one validation and two untouched test seasons."""

    if len(dataset.seasons) != 6:
        raise DatasetContractError("baseline contract requires exactly six chronological seasons")
    return ChronologicalSplit(
        history_seasons=dataset.seasons[:3],
        validation_season=dataset.seasons[3],
        test_seasons=dataset.seasons[4:],
    )
