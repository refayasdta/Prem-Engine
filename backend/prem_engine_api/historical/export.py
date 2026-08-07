"""Leakage-aware modeling exports and historical coverage reports."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from prem_engine_api.domain.enums import KickoffPrecision
from prem_engine_api.domain.models import (
    ActualResultRevision,
    Club,
    HistoricalMatchRecord,
    HistoricalSourceFile,
    Match,
    Season,
)
from prem_engine_api.historical.contracts import STATISTIC_COLUMNS

TRAINING_COLUMNS = (
    "match_uuid",
    "season",
    "kickoff_at",
    "kickoff_precision",
    "home_club_uuid",
    "home_club",
    "away_club_uuid",
    "away_club",
    "home_goals",
    "away_goals",
    "result",
    "half_time_home_goals",
    "half_time_away_goals",
    "referee",
    *STATISTIC_COLUMNS,
    "available_after",
    "lagged_history_only",
    "source_checksum",
    "source_row_number",
)


@dataclass(frozen=True)
class GeneratedArtifact:
    path: Path
    row_count: int
    checksum: str


def record_is_available(*, available_after: datetime, feature_cutoff_at: datetime) -> bool:
    """Prevent a match record from contributing to features before it was knowable."""

    return available_after < feature_cutoff_at


def _result_code(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


def _write_csv(
    path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]
) -> GeneratedArtifact:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    body = path.read_bytes()
    return GeneratedArtifact(
        path=path,
        row_count=len(rows),
        checksum=hashlib.sha256(body).hexdigest(),
    )


async def _latest_source_files(session: AsyncSession) -> tuple[HistoricalSourceFile, ...]:
    sources = list(
        await session.scalars(
            select(HistoricalSourceFile).order_by(
                HistoricalSourceFile.season_label,
                HistoricalSourceFile.retrieved_at.desc(),
                HistoricalSourceFile.created_at.desc(),
            )
        )
    )
    latest: dict[str, HistoricalSourceFile] = {}
    for source in sources:
        latest.setdefault(source.season_label, source)
    return tuple(latest[label] for label in sorted(latest))


async def _normalized_rows(session: AsyncSession) -> list[dict[str, Any]]:
    latest_sources = await _latest_source_files(session)
    if not latest_sources:
        return []
    source_ids = [source.source_file_uuid for source in latest_sources]
    home = aliased(Club)
    away = aliased(Club)
    statement = (
        select(
            HistoricalMatchRecord,
            HistoricalSourceFile,
            Match,
            Season,
            home,
            away,
            ActualResultRevision,
        )
        .join(
            HistoricalSourceFile,
            HistoricalSourceFile.source_file_uuid == HistoricalMatchRecord.source_file_uuid,
        )
        .join(Match, Match.match_uuid == HistoricalMatchRecord.match_uuid)
        .join(Season, Season.season_uuid == Match.season_uuid)
        .join(home, home.club_uuid == Match.home_club_uuid)
        .join(away, away.club_uuid == Match.away_club_uuid)
        .join(
            ActualResultRevision,
            (ActualResultRevision.match_uuid == Match.match_uuid)
            & ActualResultRevision.accepted.is_(True),
        )
        .where(HistoricalMatchRecord.source_file_uuid.in_(source_ids))
        .order_by(Match.current_kickoff_at, Match.match_uuid)
    )
    rows: list[dict[str, Any]] = []
    for record, source, match, season, home_club, away_club, result in await session.execute(
        statement
    ):
        row: dict[str, Any] = {
            "match_uuid": str(match.match_uuid),
            "season": season.label,
            "kickoff_at": match.current_kickoff_at.isoformat(),
            "kickoff_precision": match.kickoff_precision.value,
            "home_club_uuid": str(home_club.club_uuid),
            "home_club": home_club.canonical_name,
            "away_club_uuid": str(away_club.club_uuid),
            "away_club": away_club.canonical_name,
            "home_goals": result.home_goals,
            "away_goals": result.away_goals,
            "result": _result_code(result.home_goals, result.away_goals),
            "half_time_home_goals": record.half_time_home_goals,
            "half_time_away_goals": record.half_time_away_goals,
            "referee": record.referee,
            "available_after": record.available_after.isoformat(),
            "lagged_history_only": True,
            "source_checksum": source.response_checksum,
            "source_row_number": record.source_row_number,
        }
        row.update({column: record.statistics.get(column) for column in STATISTIC_COLUMNS})
        rows.append(row)
    return rows


async def export_training_matches(session: AsyncSession, path: Path) -> GeneratedArtifact:
    """Write normalized outcomes/stats; odds are deliberately excluded from training."""

    rows = await _normalized_rows(session)
    return _write_csv(path, rows, TRAINING_COLUMNS)


async def export_benchmark_odds(session: AsyncSession, path: Path) -> GeneratedArtifact:
    """Write odds separately so uncertain timing cannot leak into the training contract."""

    latest_sources = await _latest_source_files(session)
    source_ids = [source.source_file_uuid for source in latest_sources]
    rows: list[dict[str, Any]] = []
    if source_ids:
        statement = (
            select(HistoricalMatchRecord, HistoricalSourceFile)
            .join(
                HistoricalSourceFile,
                HistoricalSourceFile.source_file_uuid == HistoricalMatchRecord.source_file_uuid,
            )
            .where(HistoricalMatchRecord.source_file_uuid.in_(source_ids))
            .order_by(HistoricalSourceFile.season_label, HistoricalMatchRecord.source_row_number)
        )
        for record, source in await session.execute(statement):
            if record.benchmark_odds:
                rows.append(
                    {
                        "match_uuid": str(record.match_uuid),
                        "season": source.season_label,
                        "odds_timing": record.odds_timing,
                        "training_eligible": record.odds_training_eligible,
                        "odds_json": json.dumps(record.benchmark_odds, sort_keys=True),
                        "source_checksum": source.response_checksum,
                    }
                )
    columns = (
        "match_uuid",
        "season",
        "odds_timing",
        "training_eligible",
        "odds_json",
        "source_checksum",
    )
    return _write_csv(path, rows, columns)


async def build_coverage_report(
    session: AsyncSession, *, generated_at: datetime | None = None
) -> dict[str, Any]:
    """Measure row, time, and optional-stat availability on latest source versions."""

    sources = await _latest_source_files(session)
    seasons: list[dict[str, Any]] = []
    for source in sources:
        records = list(
            await session.scalars(
                select(HistoricalMatchRecord).where(
                    HistoricalMatchRecord.source_file_uuid == source.source_file_uuid
                )
            )
        )
        match_ids: list[UUID] = [record.match_uuid for record in records]
        matches: list[Match] = []
        if match_ids:
            matches = list(
                await session.scalars(select(Match).where(Match.match_uuid.in_(match_ids)))
            )
        exact_kickoffs = sum(match.kickoff_precision is KickoffPrecision.EXACT for match in matches)
        statistic_counts = {
            column: sum(column in record.statistics for record in records)
            for column in STATISTIC_COLUMNS
        }
        seasons.append(
            {
                "season": source.season_label,
                "source_url": source.source_url,
                "source_checksum": source.response_checksum,
                "schema_fingerprint": source.schema_fingerprint,
                "rows": len(records),
                "expected_rows": 380,
                "complete_schedule": len(records) == 380,
                "exact_kickoffs": exact_kickoffs,
                "date_only_kickoffs": len(matches) - exact_kickoffs,
                "statistic_non_null_counts": statistic_counts,
                "odds_rows": sum(bool(record.benchmark_odds) for record in records),
                "odds_training_eligible_rows": sum(
                    record.odds_training_eligible for record in records
                ),
            }
        )
    total_rows = sum(int(season["rows"]) for season in seasons)
    return {
        "contract_version": "historical-coverage-v1",
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "source_policy": {
            "raw_csv_redistributed": False,
            "normalized_training_export_contains_odds": False,
            "odds_usage": "benchmark_only_until_exact_pre_match_timing_is_proven",
            "feature_eligibility_rule": "available_after < feature_cutoff_at",
        },
        "season_count": len(seasons),
        "total_rows": total_rows,
        "seasons": seasons,
    }


def write_coverage_report(path: Path, report: dict[str, Any]) -> GeneratedArtifact:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(body)
    return GeneratedArtifact(
        path=path,
        row_count=int(report["total_rows"]),
        checksum=hashlib.sha256(body).hexdigest(),
    )
