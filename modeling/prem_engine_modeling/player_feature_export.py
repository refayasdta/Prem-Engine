"""Phase 10 player-enhanced export, validation, and coverage reporting."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from prem_engine_modeling.features import PREMATCH_FEATURE_COLUMNS
from prem_engine_modeling.player_features import (
    PLAYER_EXPORT_COLUMNS,
    PLAYER_FEATURE_COLUMNS,
    PLAYER_FEATURE_CONTRACT_VERSION,
    PlayerEnhancedFeatureDataset,
)

MIN_PERFORMANCE_RECORDS = 10_000
MIN_COVERED_FIXTURE_RATE = 0.70
MIN_TEAM_HISTORY_COVERAGE = 0.50
MIN_CANDIDATE_SQUAD_SIZE = 15


class PlayerFeatureContractError(ValueError):
    """Raised when a player-enhanced export is malformed or unsafe."""


@dataclass(frozen=True)
class PlayerCoverageDecision:
    trainable: bool
    performance_record_count: int
    covered_fixture_count: int
    covered_fixture_rate: float
    reason: str


@dataclass(frozen=True)
class PlayerFeatureExportResult:
    dataset_path: Path
    dataset_checksum: str
    report_path: Path
    report_checksum: str
    row_count: int
    feature_count: int
    coverage: PlayerCoverageDecision


@dataclass(frozen=True)
class ValidatedPlayerFeatureExport:
    checksum: str
    row_count: int
    seasons: tuple[str, ...]
    feature_count: int
    coverage: PlayerCoverageDecision


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".12g")
    return value


def render_player_feature_csv(dataset: PlayerEnhancedFeatureDataset) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=PLAYER_EXPORT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in dataset.rows:
        flat = row.as_flat_dict()
        writer.writerow({column: _csv_value(flat[column]) for column in PLAYER_EXPORT_COLUMNS})
    return stream.getvalue().encode("utf-8")


def assess_player_coverage(
    rows: list[dict[str, str]],
    *,
    performance_record_count: int,
) -> PlayerCoverageDecision:
    covered = sum(
        int(row["home_candidate_squad_size"]) >= MIN_CANDIDATE_SQUAD_SIZE
        and int(row["away_candidate_squad_size"]) >= MIN_CANDIDATE_SQUAD_SIZE
        and float(row["home_player_history_coverage"]) >= MIN_TEAM_HISTORY_COVERAGE
        and float(row["away_player_history_coverage"]) >= MIN_TEAM_HISTORY_COVERAGE
        for row in rows
    )
    rate = covered / len(rows) if rows else 0.0
    if performance_record_count < MIN_PERFORMANCE_RECORDS:
        reason = (
            f"Only {performance_record_count:,} player-match performances are available; "
            f"at least {MIN_PERFORMANCE_RECORDS:,} are required."
        )
        trainable = False
    elif rate < MIN_COVERED_FIXTURE_RATE:
        reason = (
            f"Only {rate:.1%} of fixtures have two adequately covered squads; "
            f"at least {MIN_COVERED_FIXTURE_RATE:.0%} is required."
        )
        trainable = False
    else:
        reason = "Historical player coverage passes the Phase 10 training gate."
        trainable = True
    return PlayerCoverageDecision(
        trainable=trainable,
        performance_record_count=performance_record_count,
        covered_fixture_count=covered,
        covered_fixture_rate=rate,
        reason=reason,
    )


def _aware(value: str, *, field: str, row_number: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise PlayerFeatureContractError(f"row {row_number}: invalid {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PlayerFeatureContractError(f"row {row_number}: {field} needs a timezone")
    return parsed


def validate_player_feature_export(
    path: Path,
    *,
    performance_record_count: int,
) -> ValidatedPlayerFeatureExport:
    body = path.read_bytes()
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PlayerFeatureContractError("player feature export must be UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != PLAYER_EXPORT_COLUMNS:
        raise PlayerFeatureContractError("player feature columns do not match the v1 contract")
    rows = list(reader)
    if not rows:
        raise PlayerFeatureContractError("player feature export contains no rows")
    match_ids: set[str] = set()
    seasons: list[str] = []
    closed_seasons: set[str] = set()
    ordering: list[tuple[datetime, str]] = []
    for row_number, row in enumerate(rows, 2):
        if row["player_feature_contract_version"] != PLAYER_FEATURE_CONTRACT_VERSION:
            raise PlayerFeatureContractError(
                f"row {row_number}: unsupported player feature contract"
            )
        match_uuid = row["match_uuid"]
        if not match_uuid or match_uuid in match_ids:
            raise PlayerFeatureContractError(f"row {row_number}: missing or duplicate match UUID")
        match_ids.add(match_uuid)
        kickoff = _aware(row["kickoff_at"], field="kickoff_at", row_number=row_number)
        cutoff = _aware(row["feature_cutoff_at"], field="feature_cutoff_at", row_number=row_number)
        if kickoff - cutoff != timedelta(hours=24):
            raise PlayerFeatureContractError(f"row {row_number}: cutoff is not 24 hours")
        latest = row["latest_player_input_available_after"]
        if (
            latest
            and _aware(
                latest,
                field="latest_player_input_available_after",
                row_number=row_number,
            )
            >= cutoff
        ):
            raise PlayerFeatureContractError(f"row {row_number}: player input violates cutoff")
        for column in PREMATCH_FEATURE_COLUMNS + PLAYER_FEATURE_COLUMNS:
            raw_value = row[column]
            if not raw_value and column in PREMATCH_FEATURE_COLUMNS:
                continue
            if not raw_value:
                raise PlayerFeatureContractError(
                    f"row {row_number}: missing player feature {column}"
                )
            try:
                value = float(raw_value)
            except ValueError as error:
                raise PlayerFeatureContractError(
                    f"row {row_number}: non-numeric feature {column}"
                ) from error
            if not math.isfinite(value):
                raise PlayerFeatureContractError(f"row {row_number}: non-finite feature {column}")
        season = row["season"]
        if not seasons or seasons[-1] != season:
            if season in closed_seasons:
                raise PlayerFeatureContractError("season rows must form one chronological block")
            if seasons:
                closed_seasons.add(seasons[-1])
            seasons.append(season)
        ordering.append((kickoff, match_uuid))
    if ordering != sorted(ordering):
        raise PlayerFeatureContractError("player feature export must be chronological")
    coverage = assess_player_coverage(rows, performance_record_count=performance_record_count)
    return ValidatedPlayerFeatureExport(
        checksum=hashlib.sha256(body).hexdigest(),
        row_count=len(rows),
        seasons=tuple(seasons),
        feature_count=len(PREMATCH_FEATURE_COLUMNS) + len(PLAYER_FEATURE_COLUMNS),
        coverage=coverage,
    )


def player_quality_summary(
    dataset: PlayerEnhancedFeatureDataset,
    *,
    dataset_checksum: str,
    coverage: PlayerCoverageDecision,
) -> dict[str, Any]:
    season_rows = {
        season: sum(row.base["season"] == season for row in dataset.rows)
        for season in dataset.seasons
    }
    average_features = {
        column: sum(float(row.as_flat_dict()[column]) for row in dataset.rows) / len(dataset.rows)
        for column in PLAYER_FEATURE_COLUMNS
    }
    availability_rows = sum(
        row.home.availability_report_coverage > 0 or row.away.availability_report_coverage > 0
        for row in dataset.rows
    )
    return {
        "contract_version": "player-feature-quality-v1",
        "player_feature_contract_version": PLAYER_FEATURE_CONTRACT_VERSION,
        "deterministic": True,
        "base_feature_checksum": dataset.base_feature_checksum,
        "player_context_checksum": dataset.player_context_checksum,
        "player_feature_dataset_checksum": dataset_checksum,
        "row_count": len(dataset.rows),
        "base_feature_count": len(PREMATCH_FEATURE_COLUMNS),
        "player_feature_count": len(PLAYER_FEATURE_COLUMNS),
        "total_feature_count": len(PREMATCH_FEATURE_COLUMNS) + len(PLAYER_FEATURE_COLUMNS),
        "seasons": list(dataset.seasons),
        "rows_by_season": season_rows,
        "prediction_lead_hours": 24,
        "availability_rule": "player input timestamp < feature_cutoff_at",
        "availability_observed_fixture_count": availability_rows,
        "coverage_gate": asdict(coverage),
        "average_player_features": average_features,
        "unknown_availability_policy": (
            "Missing reports remain unknown with a conservative 0.75 availability probability; "
            "they are never treated as confirmed available."
        ),
        "official_model_allowed": False,
    }


def write_player_feature_export(
    dataset: PlayerEnhancedFeatureDataset,
    *,
    performance_record_count: int,
    dataset_path: Path,
    report_path: Path,
    force: bool = False,
    created_at: datetime | None = None,
) -> PlayerFeatureExportResult:
    if not force and (dataset_path.exists() or report_path.exists()):
        raise FileExistsError("player feature export exists; pass --force to replace it")
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    body = render_player_feature_csv(dataset)
    dataset_path.write_bytes(body)
    validated = validate_player_feature_export(
        dataset_path,
        performance_record_count=performance_record_count,
    )
    summary = player_quality_summary(
        dataset,
        dataset_checksum=validated.checksum,
        coverage=validated.coverage,
    )
    summary.update(
        {
            "created_at": (created_at or datetime.now(UTC)).isoformat(),
            "dataset_path": dataset_path.as_posix(),
            "report_path": report_path.as_posix(),
        }
    )
    report_body = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(report_body)
    return PlayerFeatureExportResult(
        dataset_path=dataset_path,
        dataset_checksum=validated.checksum,
        report_path=report_path,
        report_checksum=hashlib.sha256(report_body).hexdigest(),
        row_count=validated.row_count,
        feature_count=validated.feature_count,
        coverage=validated.coverage,
    )


def human_player_feature_report(result: PlayerFeatureExportResult) -> str:
    verdict = "READY FOR TRAINING" if result.coverage.trainable else "TRAINING BLOCKED"
    return "\n".join(
        [
            "",
            "PREM ENGINE - PHASE 10 PLAYER CONTEXT",
            "=" * 76,
            f"Status                    {verdict}",
            f"Rows                      {result.row_count:,} fixtures",
            f"Total model features      {result.feature_count}",
            f"Player performances       {result.coverage.performance_record_count:,}",
            (
                "Covered fixtures          "
                f"{result.coverage.covered_fixture_count:,} "
                f"({result.coverage.covered_fixture_rate:.1%})"
            ),
            "",
            "COVERAGE DECISION",
            f"  {result.coverage.reason}",
            "",
            "SAFETY RULES",
            "  Player performances become usable only after available_after.",
            "  Availability and transfer observations must predate the 24-hour cutoff.",
            "  Missing injury data remains unknown; it never means confirmed available.",
            "  New transfers receive reduced confidence until Premier League evidence grows.",
            "",
            "OUTPUTS",
            f"  Feature CSV              {result.dataset_path}",
            f"  Quality report           {result.report_path}",
            f"  Feature SHA-256          {result.dataset_checksum}",
            "=" * 76,
        ]
    )
