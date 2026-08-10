"""Coverage-gated Phase 10 player-enhanced model training."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np

from prem_engine_modeling.data import MatchResult
from prem_engine_modeling.features import PREMATCH_FEATURE_COLUMNS
from prem_engine_modeling.player_feature_export import (
    PlayerCoverageDecision,
    validate_player_feature_export,
)
from prem_engine_modeling.player_features import PLAYER_FEATURE_COLUMNS
from prem_engine_modeling.tabular_data import CLASS_ORDER, TabularDataset, TabularSplit
from prem_engine_modeling.tabular_training import (
    CandidateGrid,
    TabularTrainingResult,
    train_tabular_model,
)


class PlayerTrainingContractError(ValueError):
    """Raised when the feature and quality reports do not describe one dataset."""


class InsufficientPlayerCoverageError(RuntimeError):
    """Raised before fitting when historical player evidence is inadequate."""


@dataclass(frozen=True)
class PlayerImpactDataset:
    tabular: TabularDataset
    coverage: PlayerCoverageDecision
    player_context_checksum: str
    base_feature_checksum: str


def _split(seasons: tuple[str, ...]) -> TabularSplit:
    if len(seasons) != 6:
        raise PlayerTrainingContractError("Phase 10 requires exactly six chronological seasons")
    return TabularSplit(
        development_folds=(
            ((seasons[0],), seasons[1]),
            ((seasons[0], seasons[1]), seasons[2]),
        ),
        base_training_seasons=seasons[:3],
        calibration_season=seasons[3],
        holdout_seasons=seasons[4:],
    )


def load_player_impact_dataset(dataset_path: Path, report_path: Path) -> PlayerImpactDataset:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise PlayerTrainingContractError("player quality report must contain an object")
    gate = report.get("coverage_gate")
    if not isinstance(gate, dict):
        raise PlayerTrainingContractError("player quality report has no coverage gate")
    performance_count = gate.get("performance_record_count")
    if not isinstance(performance_count, int):
        raise PlayerTrainingContractError("coverage gate has no performance record count")
    validated = validate_player_feature_export(
        dataset_path,
        performance_record_count=performance_count,
    )
    if report.get("player_feature_dataset_checksum") != validated.checksum:
        raise PlayerTrainingContractError("quality report checksum does not match the dataset")
    if bool(gate.get("trainable")) != validated.coverage.trainable:
        raise PlayerTrainingContractError("quality report coverage verdict is stale")
    base_checksum = report.get("base_feature_checksum")
    context_checksum = report.get("player_context_checksum")
    if not isinstance(base_checksum, str) or not isinstance(context_checksum, str):
        raise PlayerTrainingContractError("quality report is missing source checksums")

    feature_columns = PREMATCH_FEATURE_COLUMNS + PLAYER_FEATURE_COLUMNS
    rows: list[list[float]] = []
    targets: list[int] = []
    match_uuids: list[str] = []
    seasons_by_row: list[str] = []
    kickoffs: list[str] = []
    with dataset_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            rows.append(
                [float(row[column]) if row[column] else np.nan for column in feature_columns]
            )
            result = cast(MatchResult, row["target_result"])
            targets.append(CLASS_ORDER.index(result))
            match_uuids.append(row["match_uuid"])
            seasons_by_row.append(row["season"])
            kickoffs.append(row["kickoff_at"])
    features = np.asarray(rows, dtype=np.float64)
    target_array = np.asarray(targets, dtype=np.int64)
    if features.shape != (validated.row_count, validated.feature_count):
        raise PlayerTrainingContractError("player feature matrix contradicts its contract")
    if not np.isfinite(features[~np.isnan(features)]).all():
        raise PlayerTrainingContractError("player feature matrix contains non-finite values")
    tabular = TabularDataset(
        features=features,
        targets=target_array,
        match_uuids=tuple(match_uuids),
        seasons_by_row=tuple(seasons_by_row),
        kickoffs=tuple(kickoffs),
        feature_columns=feature_columns,
        checksum=validated.checksum,
        seasons=validated.seasons,
        split=_split(validated.seasons),
    )
    return PlayerImpactDataset(
        tabular=tabular,
        coverage=validated.coverage,
        player_context_checksum=context_checksum,
        base_feature_checksum=base_checksum,
    )


def train_player_impact_model(
    dataset: PlayerImpactDataset,
    *,
    candidate_grid: CandidateGrid | None = None,
) -> TabularTrainingResult:
    if not dataset.coverage.trainable:
        raise InsufficientPlayerCoverageError(dataset.coverage.reason)
    return train_tabular_model(dataset.tabular, candidate_grid=candidate_grid)
