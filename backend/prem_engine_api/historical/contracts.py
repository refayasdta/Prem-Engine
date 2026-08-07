"""Strict contracts for season CSV files published by Football-Data.co.uk."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any


class HistoricalDataError(ValueError):
    """Raised when a source file cannot safely be normalized."""


STATISTIC_COLUMNS = (
    "HS",
    "AS",
    "HST",
    "AST",
    "HC",
    "AC",
    "HF",
    "AF",
    "HY",
    "AY",
    "HR",
    "AR",
)

BENCHMARK_ODDS_COLUMNS = (
    "B365H",
    "B365D",
    "B365A",
    "B365CH",
    "B365CD",
    "B365CA",
    "PSH",
    "PSD",
    "PSA",
    "PSCH",
    "PSCD",
    "PSCA",
    "AvgH",
    "AvgD",
    "AvgA",
    "AvgCH",
    "AvgCD",
    "AvgCA",
)

REQUIRED_COLUMNS = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"}


@dataclass(frozen=True)
class HistoricalMatchRow:
    """One validated source row with stable provenance."""

    source_row_number: int
    division: str | None
    match_date: date
    match_time: time | None
    home_team: str
    away_team: str
    full_time_home_goals: int
    full_time_away_goals: int
    full_time_result: str
    half_time_home_goals: int | None
    half_time_away_goals: int | None
    referee: str | None
    statistics: dict[str, int]
    benchmark_odds: dict[str, float]
    row_checksum: str


@dataclass(frozen=True)
class ParsedHistoricalFile:
    """Validated file plus a fingerprint of its exact ordered header contract."""

    headers: tuple[str, ...]
    schema_fingerprint: str
    rows: tuple[HistoricalMatchRow, ...]


def _decode_csv(body: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HistoricalDataError("source CSV is neither UTF-8 nor Windows-1252")


def _required_text(row: dict[str, str | None], column: str, row_number: int) -> str:
    value = (row.get(column) or "").strip()
    if not value:
        raise HistoricalDataError(f"row {row_number}: {column} is required")
    return value


def _optional_text(row: dict[str, str | None], column: str) -> str | None:
    value = (row.get(column) or "").strip()
    return value or None


def _integer(value: str, *, column: str, row_number: int) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise HistoricalDataError(f"row {row_number}: {column} must be an integer") from error
    if parsed < 0:
        raise HistoricalDataError(f"row {row_number}: {column} cannot be negative")
    return parsed


def _optional_integer(row: dict[str, str | None], column: str, row_number: int) -> int | None:
    value = _optional_text(row, column)
    return None if value is None else _integer(value, column=column, row_number=row_number)


def _optional_float(row: dict[str, str | None], column: str, row_number: int) -> float | None:
    value = _optional_text(row, column)
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError as error:
        raise HistoricalDataError(f"row {row_number}: {column} must be numeric") from error
    if parsed <= 0:
        raise HistoricalDataError(f"row {row_number}: {column} must be positive")
    return parsed


def _match_date(value: str, row_number: int) -> date:
    for pattern in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise HistoricalDataError(f"row {row_number}: Date must use dd/mm/yy or dd/mm/yyyy")


def _match_time(value: str | None, row_number: int) -> time | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as error:
        raise HistoricalDataError(f"row {row_number}: Time must use HH:MM") from error


def _result_for(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


def _row_checksum(row: dict[str, str | None], headers: tuple[str, ...]) -> str:
    canonical: dict[str, str] = {header: (row.get(header) or "").strip() for header in headers}
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_row(
    row: dict[str, str | None], headers: tuple[str, ...], row_number: int
) -> HistoricalMatchRow:
    match_date = _match_date(_required_text(row, "Date", row_number), row_number)
    match_time = _match_time(_optional_text(row, "Time"), row_number)
    home_goals = _integer(
        _required_text(row, "FTHG", row_number), column="FTHG", row_number=row_number
    )
    away_goals = _integer(
        _required_text(row, "FTAG", row_number), column="FTAG", row_number=row_number
    )
    result = _required_text(row, "FTR", row_number).upper()
    if result not in {"H", "D", "A"}:
        raise HistoricalDataError(f"row {row_number}: FTR must be H, D, or A")
    if result != _result_for(home_goals, away_goals):
        raise HistoricalDataError(f"row {row_number}: FTR contradicts the full-time score")

    half_home = _optional_integer(row, "HTHG", row_number)
    half_away = _optional_integer(row, "HTAG", row_number)
    half_result = _optional_text(row, "HTR")
    if (half_home is None) != (half_away is None):
        raise HistoricalDataError(f"row {row_number}: both half-time goal values are required")
    if half_result is not None:
        if half_home is None or half_away is None:
            raise HistoricalDataError(f"row {row_number}: HTR requires half-time goals")
        if half_result.upper() != _result_for(half_home, half_away):
            raise HistoricalDataError(f"row {row_number}: HTR contradicts the half-time score")

    statistics: dict[str, int] = {}
    for column in STATISTIC_COLUMNS:
        statistic_value = _optional_integer(row, column, row_number)
        if statistic_value is not None:
            statistics[column] = statistic_value
    benchmark_odds: dict[str, float] = {}
    for column in BENCHMARK_ODDS_COLUMNS:
        odds_value = _optional_float(row, column, row_number)
        if odds_value is not None:
            benchmark_odds[column] = odds_value
    return HistoricalMatchRow(
        source_row_number=row_number,
        division=_optional_text(row, "Div"),
        match_date=match_date,
        match_time=match_time,
        home_team=_required_text(row, "HomeTeam", row_number),
        away_team=_required_text(row, "AwayTeam", row_number),
        full_time_home_goals=home_goals,
        full_time_away_goals=away_goals,
        full_time_result=result,
        half_time_home_goals=half_home,
        half_time_away_goals=half_away,
        referee=_optional_text(row, "Referee"),
        statistics=statistics,
        benchmark_odds=benchmark_odds,
        row_checksum=_row_checksum(row, headers),
    )


def parse_historical_csv(body: bytes) -> ParsedHistoricalFile:
    """Decode and validate a complete CSV before any normalized record is written."""

    text = _decode_csv(body)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        raise HistoricalDataError("source CSV has no header row")
    headers = tuple(header.strip() for header in reader.fieldnames if header is not None)
    if len(headers) != len(reader.fieldnames) or len(headers) != len(set(headers)):
        raise HistoricalDataError("source CSV contains blank or duplicate headers")
    missing = sorted(REQUIRED_COLUMNS.difference(headers))
    if missing:
        raise HistoricalDataError(f"source CSV is missing required columns: {', '.join(missing)}")

    rows: list[HistoricalMatchRow] = []
    for row_number, raw_row in enumerate(reader, start=2):
        if None in raw_row:
            raise HistoricalDataError(f"row {row_number}: contains more values than headers")
        if not any((value or "").strip() for value in raw_row.values()):
            continue
        rows.append(_parse_row(raw_row, headers, row_number))
    if not rows:
        raise HistoricalDataError("source CSV contains no match rows")

    schema_payload: dict[str, Any] = {"headers": headers}
    schema_fingerprint = hashlib.sha256(
        json.dumps(schema_payload, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ParsedHistoricalFile(
        headers=headers,
        schema_fingerprint=schema_fingerprint,
        rows=tuple(rows),
    )
