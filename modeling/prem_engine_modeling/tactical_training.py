"""Coverage-gated Phase 15 tactical model training."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np

from prem_engine_modeling.data import MatchResult
from prem_engine_modeling.features import PREMATCH_FEATURE_COLUMNS
from prem_engine_modeling.player_features import PLAYER_FEATURE_COLUMNS
from prem_engine_modeling.tabular_data import CLASS_ORDER, TabularDataset, TabularSplit
from prem_engine_modeling.tabular_training import (
    CandidateGrid,
    TabularTrainingResult,
    train_tabular_model,
)
from prem_engine_modeling.tactical_feature_export import (
    TacticalCoverageDecision,
    validate_tactical_feature_export,
)
from prem_engine_modeling.tactical_features import TACTICAL_FEATURE_COLUMNS


class TacticalTrainingContractError(ValueError):
    """Raised when a tactical dataset and its quality report disagree."""


class InsufficientTacticalCoverageError(RuntimeError):
    """Raised before fitting if audited tactical evidence is inadequate."""


@dataclass(frozen=True)
class TacticalTrainingDataset:
    tabular: TabularDataset
    coverage: TacticalCoverageDecision
    player_feature_checksum: str
    historical_match_checksum: str
    player_context_checksum: str


def _split(seasons: tuple[str, ...]) -> TabularSplit:
    if len(seasons) != 6:
        raise TacticalTrainingContractError("Phase 15 requires six chronological seasons")
    return TabularSplit(
        development_folds=(
            ((seasons[0],), seasons[1]),
            ((seasons[0], seasons[1]), seasons[2]),
        ),
        base_training_seasons=seasons[:3],
        calibration_season=seasons[3],
        holdout_seasons=seasons[4:],
    )


def load_tactical_training_dataset(
    dataset_path: Path, report_path: Path
) -> TacticalTrainingDataset:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise TacticalTrainingContractError("tactical quality report must contain an object")
    gate = report.get("coverage_gate")
    if not isinstance(gate, dict) or not isinstance(gate.get("shape_observation_count"), int):
        raise TacticalTrainingContractError("tactical quality report has no coverage gate")
    validated = validate_tactical_feature_export(
        dataset_path, shape_observation_count=gate["shape_observation_count"]
    )
    if report.get("tactical_feature_dataset_checksum") != validated.checksum:
        raise TacticalTrainingContractError("quality report checksum does not match the dataset")
    if bool(gate.get("trainable")) != validated.coverage.trainable:
        raise TacticalTrainingContractError("quality report coverage verdict is stale")
    source_keys = (
        "player_feature_checksum",
        "historical_match_checksum",
        "player_context_checksum",
    )
    if any(not isinstance(report.get(key), str) for key in source_keys):
        raise TacticalTrainingContractError("quality report is missing source checksums")

    feature_columns = PREMATCH_FEATURE_COLUMNS + PLAYER_FEATURE_COLUMNS + TACTICAL_FEATURE_COLUMNS
    rows: list[list[float]] = []
    targets: list[int] = []
    match_uuids: list[str] = []
    seasons_by_row: list[str] = []
    kickoffs: list[str] = []
    with dataset_path.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            rows.append(
                [float(row[column]) if row[column] else np.nan for column in feature_columns]
            )
            result = cast(MatchResult, row["target_result"])
            targets.append(CLASS_ORDER.index(result))
            match_uuids.append(row["match_uuid"])
            seasons_by_row.append(row["season"])
            kickoffs.append(row["kickoff_at"])
    features = np.asarray(rows, dtype=np.float64)
    if features.shape != (validated.row_count, validated.feature_count):
        raise TacticalTrainingContractError("tactical feature matrix contradicts its contract")
    if not np.isfinite(features[~np.isnan(features)]).all():
        raise TacticalTrainingContractError("tactical feature matrix contains non-finite values")
    tabular = TabularDataset(
        features=features,
        targets=np.asarray(targets, dtype=np.int64),
        match_uuids=tuple(match_uuids),
        seasons_by_row=tuple(seasons_by_row),
        kickoffs=tuple(kickoffs),
        feature_columns=feature_columns,
        checksum=validated.checksum,
        seasons=validated.seasons,
        split=_split(validated.seasons),
    )
    return TacticalTrainingDataset(
        tabular=tabular,
        coverage=validated.coverage,
        player_feature_checksum=str(report["player_feature_checksum"]),
        historical_match_checksum=str(report["historical_match_checksum"]),
        player_context_checksum=str(report["player_context_checksum"]),
    )


def train_tactical_model(
    dataset: TacticalTrainingDataset,
    *,
    candidate_grid: CandidateGrid | None = None,
) -> TabularTrainingResult:
    if not dataset.coverage.trainable:
        raise InsufficientTacticalCoverageError(dataset.coverage.reason)
    return train_tabular_model(dataset.tabular, candidate_grid=candidate_grid)
