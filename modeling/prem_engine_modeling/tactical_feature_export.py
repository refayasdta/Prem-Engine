"""Phase 15 tactical feature export, validation, and coverage gates."""

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
from prem_engine_modeling.player_features import PLAYER_FEATURE_COLUMNS
from prem_engine_modeling.tactical_features import (
    TACTICAL_EXPORT_COLUMNS,
    TACTICAL_FEATURE_COLUMNS,
    TACTICAL_FEATURE_CONTRACT_VERSION,
    TacticalFeatureDataset,
)

MIN_STYLE_COVERAGE = 0.90
MIN_SHAPE_COVERAGE = 0.45
MIN_RECENT_SAMPLES = 3


class TacticalFeatureContractError(ValueError):
    """Raised when a tactical export is malformed, stale, or leaky."""


@dataclass(frozen=True)
class TacticalCoverageDecision:
    trainable: bool
    style_covered_fixture_count: int
    style_covered_fixture_rate: float
    shape_covered_fixture_count: int
    shape_covered_fixture_rate: float
    shape_observation_count: int
    reason: str


@dataclass(frozen=True)
class ValidatedTacticalFeatureExport:
    checksum: str
    row_count: int
    seasons: tuple[str, ...]
    feature_count: int
    coverage: TacticalCoverageDecision


@dataclass(frozen=True)
class TacticalFeatureExportResult:
    dataset_path: Path
    dataset_checksum: str
    report_path: Path
    report_checksum: str
    row_count: int
    feature_count: int
    coverage: TacticalCoverageDecision
    source_statistic_anomaly_count: int


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".12g")
    return value


def render_tactical_feature_csv(dataset: TacticalFeatureDataset) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=TACTICAL_EXPORT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in dataset.rows:
        flat = row.as_flat_dict()
        writer.writerow({column: _csv_value(flat[column]) for column in TACTICAL_EXPORT_COLUMNS})
    return stream.getvalue().encode("utf-8")


def assess_tactical_coverage(
    rows: list[dict[str, str]], *, shape_observation_count: int
) -> TacticalCoverageDecision:
    style_covered = sum(
        int(row["home_style_sample_count"]) >= MIN_RECENT_SAMPLES
        and int(row["away_style_sample_count"]) >= MIN_RECENT_SAMPLES
        for row in rows
    )
    shape_covered = sum(
        int(row["home_shape_sample_count"]) >= MIN_RECENT_SAMPLES
        and int(row["away_shape_sample_count"]) >= MIN_RECENT_SAMPLES
        for row in rows
    )
    total = len(rows)
    style_rate = style_covered / total if total else 0.0
    shape_rate = shape_covered / total if total else 0.0
    if style_rate < MIN_STYLE_COVERAGE:
        trainable = False
        reason = (
            f"Only {style_rate:.1%} of fixtures have three prior style observations per club; "
            f"at least {MIN_STYLE_COVERAGE:.0%} is required."
        )
    elif shape_rate < MIN_SHAPE_COVERAGE:
        trainable = False
        reason = (
            f"Only {shape_rate:.1%} of fixtures have three observed prior XIs per club; "
            f"at least {MIN_SHAPE_COVERAGE:.0%} is required."
        )
    else:
        trainable = True
        reason = "Historical style and observed-XI coverage pass the Phase 15 training gate."
    return TacticalCoverageDecision(
        trainable=trainable,
        style_covered_fixture_count=style_covered,
        style_covered_fixture_rate=style_rate,
        shape_covered_fixture_count=shape_covered,
        shape_covered_fixture_rate=shape_rate,
        shape_observation_count=shape_observation_count,
        reason=reason,
    )


def _aware(value: str, *, field: str, row_number: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise TacticalFeatureContractError(f"row {row_number}: invalid {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TacticalFeatureContractError(f"row {row_number}: {field} needs a timezone")
    return parsed


def validate_tactical_feature_export(
    path: Path, *, shape_observation_count: int
) -> ValidatedTacticalFeatureExport:
    body = path.read_bytes()
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TacticalFeatureContractError("tactical export must be UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != TACTICAL_EXPORT_COLUMNS:
        raise TacticalFeatureContractError("tactical feature columns do not match the v1 contract")
    rows = list(reader)
    if not rows:
        raise TacticalFeatureContractError("tactical feature export contains no rows")
    seen: set[str] = set()
    seasons: list[str] = []
    closed: set[str] = set()
    ordering: list[tuple[datetime, str]] = []
    for row_number, row in enumerate(rows, 2):
        if row["tactical_feature_contract_version"] != TACTICAL_FEATURE_CONTRACT_VERSION:
            raise TacticalFeatureContractError(f"row {row_number}: unsupported tactical contract")
        match_uuid = row["match_uuid"]
        if not match_uuid or match_uuid in seen:
            raise TacticalFeatureContractError(f"row {row_number}: missing or duplicate match UUID")
        seen.add(match_uuid)
        kickoff = _aware(row["kickoff_at"], field="kickoff_at", row_number=row_number)
        cutoff = _aware(row["feature_cutoff_at"], field="feature_cutoff_at", row_number=row_number)
        if kickoff - cutoff != timedelta(hours=24):
            raise TacticalFeatureContractError(f"row {row_number}: cutoff is not 24 hours")
        latest = row["latest_tactical_input_available_after"]
        if (
            latest
            and _aware(latest, field="latest tactical input", row_number=row_number) >= cutoff
        ):
            raise TacticalFeatureContractError(f"row {row_number}: tactical input violates cutoff")
        for column in PREMATCH_FEATURE_COLUMNS + PLAYER_FEATURE_COLUMNS + TACTICAL_FEATURE_COLUMNS:
            raw = row[column]
            if not raw and column in PREMATCH_FEATURE_COLUMNS:
                continue
            try:
                value = float(raw)
            except ValueError as error:
                raise TacticalFeatureContractError(
                    f"row {row_number}: missing or non-numeric feature {column}"
                ) from error
            if not math.isfinite(value):
                raise TacticalFeatureContractError(f"row {row_number}: non-finite feature {column}")
        season = row["season"]
        if not seasons or seasons[-1] != season:
            if season in closed:
                raise TacticalFeatureContractError("season rows must form one chronological block")
            if seasons:
                closed.add(seasons[-1])
            seasons.append(season)
        ordering.append((kickoff, match_uuid))
    if ordering != sorted(ordering):
        raise TacticalFeatureContractError("tactical export must be chronological")
    coverage = assess_tactical_coverage(rows, shape_observation_count=shape_observation_count)
    return ValidatedTacticalFeatureExport(
        checksum=hashlib.sha256(body).hexdigest(),
        row_count=len(rows),
        seasons=tuple(seasons),
        feature_count=(
            len(PREMATCH_FEATURE_COLUMNS)
            + len(PLAYER_FEATURE_COLUMNS)
            + len(TACTICAL_FEATURE_COLUMNS)
        ),
        coverage=coverage,
    )


def tactical_quality_summary(
    dataset: TacticalFeatureDataset,
    *,
    dataset_checksum: str,
    coverage: TacticalCoverageDecision,
) -> dict[str, Any]:
    return {
        "contract_version": "tactical-feature-quality-v1",
        "tactical_feature_contract_version": TACTICAL_FEATURE_CONTRACT_VERSION,
        "deterministic": True,
        "player_feature_checksum": dataset.player_feature_checksum,
        "historical_match_checksum": dataset.historical_match_checksum,
        "player_context_checksum": dataset.player_context_checksum,
        "tactical_feature_dataset_checksum": dataset_checksum,
        "row_count": len(dataset.rows),
        "tactical_feature_count": len(TACTICAL_FEATURE_COLUMNS),
        "total_feature_count": (
            len(PREMATCH_FEATURE_COLUMNS)
            + len(PLAYER_FEATURE_COLUMNS)
            + len(TACTICAL_FEATURE_COLUMNS)
        ),
        "seasons": list(dataset.seasons),
        "rows_by_season": {
            season: sum(row.player_row["season"] == season for row in dataset.rows)
            for season in dataset.seasons
        },
        "prediction_lead_hours": 24,
        "availability_rule": "match and lineup observations available_after < feature_cutoff_at",
        "coverage_gate": asdict(coverage),
        "source_statistic_anomaly_count": dataset.statistic_anomaly_count,
        "source_statistic_anomaly_policy": (
            "Shots on target are capped at total shots for derived rates; source rows remain "
            "unchanged and checksummed."
        ),
        "interpretation": {
            "shape": "Position-group shape inferred only from observed starting XIs.",
            "style": (
                "Shots, shots on target, corners, and fouls are measurable proxies, "
                "not subjective tactical labels."
            ),
            "causality": (
                "Feature influence is association, not proof that a tactic caused a result."
            ),
        },
        "official_model_allowed": False,
    }


def write_tactical_feature_export(
    dataset: TacticalFeatureDataset,
    *,
    dataset_path: Path,
    report_path: Path,
    force: bool = False,
    created_at: datetime | None = None,
) -> TacticalFeatureExportResult:
    if not force and (dataset_path.exists() or report_path.exists()):
        raise FileExistsError("tactical feature export exists; pass --force to replace it")
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    body = render_tactical_feature_csv(dataset)
    dataset_path.write_bytes(body)
    validated = validate_tactical_feature_export(
        dataset_path, shape_observation_count=dataset.shape_observation_count
    )
    summary = tactical_quality_summary(
        dataset, dataset_checksum=validated.checksum, coverage=validated.coverage
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
    return TacticalFeatureExportResult(
        dataset_path=dataset_path,
        dataset_checksum=validated.checksum,
        report_path=report_path,
        report_checksum=hashlib.sha256(report_body).hexdigest(),
        row_count=validated.row_count,
        feature_count=validated.feature_count,
        coverage=validated.coverage,
        source_statistic_anomaly_count=dataset.statistic_anomaly_count,
    )


def human_tactical_feature_report(result: TacticalFeatureExportResult) -> str:
    coverage = result.coverage
    status = "READY FOR MANUAL TRAINING" if coverage.trainable else "TRAINING BLOCKED"
    return "\n".join(
        [
            "",
            "PREM ENGINE - PHASE 15 TACTICAL FEATURE READINESS",
            "=" * 86,
            f"Status                    {status}",
            f"Rows                      {result.row_count:,} fixtures",
            f"Total model features      {result.feature_count}",
            f"Observed starting XIs     {coverage.shape_observation_count:,} team-matches",
            f"Source stat anomalies     {result.source_statistic_anomaly_count}",
            f"Style coverage            {coverage.style_covered_fixture_rate:.1%}",
            f"Shape coverage            {coverage.shape_covered_fixture_rate:.1%}",
            "",
            "COVERAGE DECISION",
            f"  {coverage.reason}",
            "",
            "WHAT THE FEATURES MEAN",
            "  Shape is inferred from real starter position groups, never assigned by hand.",
            "  Shot and corner shares summarize prior match behaviour as style proxies.",
            "  Fouls are a behaviour count; they are not presented as a direct pressing metric.",
            "  Missing early lineup history stays visible through sample and coverage fields.",
            "  Impossible source SOT values are capped only for derived rates and counted above.",
            "",
            "OUTPUTS",
            f"  Feature CSV              {result.dataset_path}",
            f"  Quality report           {result.report_path}",
            f"  Feature SHA-256          {result.dataset_checksum}",
            "=" * 86,
        ]
    )
