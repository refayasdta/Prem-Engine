"""Deterministic Phase 8 feature export and quality summaries."""

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

from prem_engine_modeling.features import (
    EXPORT_COLUMNS,
    FEATURE_CONTRACT_VERSION,
    PREMATCH_FEATURE_COLUMNS,
    PrematchFeatureDataset,
)


@dataclass(frozen=True)
class FeatureExportResult:
    dataset_path: Path
    dataset_checksum: str
    report_path: Path
    report_checksum: str
    row_count: int
    feature_count: int


class FeatureExportContractError(ValueError):
    """Raised when a generated feature file is malformed or permits leakage."""


@dataclass(frozen=True)
class ValidatedFeatureExport:
    checksum: str
    row_count: int
    seasons: tuple[str, ...]
    feature_count: int


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".12g")
    return value


def render_feature_csv(dataset: PrematchFeatureDataset) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in dataset.rows:
        flat = row.as_flat_dict()
        writer.writerow({column: _csv_value(flat[column]) for column in EXPORT_COLUMNS})
    return stream.getvalue().encode("utf-8")


def _aware(value: str, *, field: str, row_number: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise FeatureExportContractError(f"row {row_number}: invalid {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FeatureExportContractError(f"row {row_number}: {field} needs a timezone")
    return parsed


def validate_feature_export(path: Path) -> ValidatedFeatureExport:
    """Reject schema drift, invalid targets, ordering errors, and cutoff leakage."""

    body = path.read_bytes()
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FeatureExportContractError("feature export must be UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != EXPORT_COLUMNS:
        raise FeatureExportContractError("feature export columns do not match the v1 contract")
    rows = list(reader)
    if not rows:
        raise FeatureExportContractError("feature export contains no rows")
    match_ids: set[str] = set()
    seasons: list[str] = []
    closed_seasons: set[str] = set()
    ordering: list[tuple[datetime, str]] = []
    for row_number, row in enumerate(rows, 2):
        if row["feature_contract_version"] != FEATURE_CONTRACT_VERSION:
            raise FeatureExportContractError(
                f"row {row_number}: unsupported feature contract version"
            )
        match_uuid = row["match_uuid"]
        if not match_uuid or match_uuid in match_ids:
            raise FeatureExportContractError(f"row {row_number}: missing or duplicate match UUID")
        match_ids.add(match_uuid)
        kickoff = _aware(row["kickoff_at"], field="kickoff_at", row_number=row_number)
        cutoff = _aware(row["feature_cutoff_at"], field="feature_cutoff_at", row_number=row_number)
        try:
            lead_hours = float(row["prediction_lead_hours"])
        except ValueError as error:
            raise FeatureExportContractError(
                f"row {row_number}: invalid prediction lead"
            ) from error
        if lead_hours != 24.0 or kickoff - cutoff != timedelta(hours=lead_hours):
            raise FeatureExportContractError(f"row {row_number}: cutoff is not 24 hours")
        latest = row["latest_input_available_after"]
        if (
            latest
            and _aware(latest, field="latest_input_available_after", row_number=row_number)
            >= cutoff
        ):
            raise FeatureExportContractError(f"row {row_number}: input violates feature cutoff")
        for column in PREMATCH_FEATURE_COLUMNS:
            value = row[column]
            if value:
                try:
                    numeric = float(value)
                except ValueError as error:
                    raise FeatureExportContractError(
                        f"row {row_number}: non-numeric feature {column}"
                    ) from error
                if not math.isfinite(numeric):
                    raise FeatureExportContractError(
                        f"row {row_number}: non-finite feature {column}"
                    )
        try:
            home_goals = int(row["target_home_goals"])
            away_goals = int(row["target_away_goals"])
        except ValueError as error:
            raise FeatureExportContractError(f"row {row_number}: invalid goal target") from error
        if home_goals < 0 or away_goals < 0 or row["target_result"] not in ("H", "D", "A"):
            raise FeatureExportContractError(f"row {row_number}: invalid target")
        expected_result = (
            "H" if home_goals > away_goals else "A" if home_goals < away_goals else "D"
        )
        if row["target_result"] != expected_result:
            raise FeatureExportContractError(f"row {row_number}: target contradicts score")
        season = row["season"]
        if not seasons or seasons[-1] != season:
            if season in closed_seasons:
                raise FeatureExportContractError("season rows must form one chronological block")
            if seasons:
                closed_seasons.add(seasons[-1])
            seasons.append(season)
        ordering.append((kickoff, match_uuid))
    if ordering != sorted(ordering):
        raise FeatureExportContractError("feature export must be chronologically ordered")
    return ValidatedFeatureExport(
        checksum=hashlib.sha256(body).hexdigest(),
        row_count=len(rows),
        seasons=tuple(seasons),
        feature_count=len(PREMATCH_FEATURE_COLUMNS),
    )


def feature_quality_summary(
    dataset: PrematchFeatureDataset,
    *,
    dataset_checksum: str,
) -> dict[str, Any]:
    flat_rows = tuple(row.as_flat_dict() for row in dataset.rows)
    missing_counts = {
        column: sum(row[column] is None for row in flat_rows) for column in PREMATCH_FEATURE_COLUMNS
    }
    season_rows = {
        season: sum(row.match.season == season for row in dataset.rows)
        for season in dataset.seasons
    }
    cold_start_rows = sum(
        row.home.history_match_count == 0 or row.away.history_match_count == 0
        for row in dataset.rows
    )
    insufficient_form_rows = sum(
        row.home.missing_form_last_5 or row.away.missing_form_last_5 for row in dataset.rows
    )
    cutoff_violations = sum(
        row.latest_input_available_after is not None
        and row.latest_input_available_after >= row.feature_cutoff_at
        for row in dataset.rows
    )
    return {
        "contract_version": "prematch-feature-quality-v1",
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "deterministic": True,
        "source_dataset_checksum": dataset.source_dataset_checksum,
        "feature_dataset_checksum": dataset_checksum,
        "row_count": len(dataset.rows),
        "feature_count": len(PREMATCH_FEATURE_COLUMNS),
        "column_count": len(EXPORT_COLUMNS),
        "seasons": list(dataset.seasons),
        "rows_by_season": season_rows,
        "prediction_lead_hours": dataset.config.prediction_lead.total_seconds() / 3600,
        "availability_rule": "source.available_after < feature_cutoff_at",
        "cutoff_violation_count": cutoff_violations,
        "cold_start_row_count": cold_start_rows,
        "insufficient_five_match_form_row_count": insufficient_form_rows,
        "missing_value_counts": missing_counts,
        "model_configs": {
            "elo": asdict(dataset.config.elo),
            "goals": asdict(dataset.config.goals),
        },
        "target_columns": ["target_home_goals", "target_away_goals", "target_result"],
        "excluded_inputs": [
            "betting_odds",
            "future_results",
            "injuries",
            "suspensions",
            "players",
            "transfers",
            "expected_lineups",
            "tactical_labels",
        ],
    }


def write_feature_export(
    dataset: PrematchFeatureDataset,
    *,
    dataset_path: Path,
    report_path: Path,
    force: bool = False,
    created_at: datetime | None = None,
) -> FeatureExportResult:
    if not force and (dataset_path.exists() or report_path.exists()):
        raise FileExistsError("feature export already exists; pass --force to replace it")
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    body = render_feature_csv(dataset)
    dataset_checksum = hashlib.sha256(body).hexdigest()
    summary = feature_quality_summary(dataset, dataset_checksum=dataset_checksum)
    summary.update(
        {
            "created_at": (created_at or datetime.now(UTC)).isoformat(),
            "dataset_path": dataset_path.as_posix(),
            "report_path": report_path.as_posix(),
        }
    )
    report_body = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    dataset_path.write_bytes(body)
    report_path.write_bytes(report_body)
    return FeatureExportResult(
        dataset_path=dataset_path,
        dataset_checksum=dataset_checksum,
        report_path=report_path,
        report_checksum=hashlib.sha256(report_body).hexdigest(),
        row_count=len(dataset.rows),
        feature_count=len(PREMATCH_FEATURE_COLUMNS),
    )


def human_feature_report(
    dataset: PrematchFeatureDataset,
    result: FeatureExportResult,
) -> str:
    cold_starts = sum(
        row.home.history_match_count == 0 or row.away.history_match_count == 0
        for row in dataset.rows
    )
    insufficient = sum(
        row.home.missing_form_last_5 or row.away.missing_form_last_5 for row in dataset.rows
    )
    violations = sum(
        row.latest_input_available_after is not None
        and row.latest_input_available_after >= row.feature_cutoff_at
        for row in dataset.rows
    )
    lines = [
        "",
        "PREM ENGINE - PHASE 8 PRE-MATCH FEATURES",
        "=" * 76,
        "Status                    FEATURE EXPORT COMPLETED SUCCESSFULLY",
        f"Rows                      {result.row_count:,} fixtures",
        f"Model-ready features      {result.feature_count}",
        f"Seasons                   {', '.join(dataset.seasons)}",
        (
            "Prediction cutoff         "
            f"{dataset.config.prediction_lead.total_seconds() / 3600:.0f} hours before kickoff"
        ),
        "Availability rule         available_after < feature_cutoff_at",
        "",
        "QUALITY CHECKS",
        f"  Cutoff violations        {violations} (must be zero)",
        f"  Cold-start rows          {cold_starts}",
        f"  Rows lacking 5 matches   {insufficient}",
        "  Missing early history is represented with explicit flags, not invented values.",
        "",
        "FEATURE GROUPS",
        "  Phase 6 Elo probabilities and ratings",
        "  Phase 7 expected goals, outcome probabilities, attack and defence",
        "  Rolling 3/5/10-match form, goals, outcomes, and opponent adjustment",
        "  Rest, 7/14/30-day congestion, venue form, promotion, and confidence",
        "",
        "OUTPUTS",
        f"  Feature CSV              {result.dataset_path}",
        f"  Quality report           {result.report_path}",
        f"  Feature SHA-256          {result.dataset_checksum}",
        "",
        "LIMITATIONS",
        "  Player strength, injuries, suspensions, transfers, expected lineups,",
        "  and tactics are intentionally not included in this phase.",
        "=" * 76,
    ]
    return "\n".join(lines)
