"""Strict Phase 9 matrix loading from the approved Phase 8 feature contract."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
from numpy.typing import NDArray

from prem_engine_modeling.data import MatchResult
from prem_engine_modeling.feature_export import validate_feature_export
from prem_engine_modeling.features import PREMATCH_FEATURE_COLUMNS

CLASS_ORDER: tuple[MatchResult, ...] = ("H", "D", "A")


class TabularDataContractError(ValueError):
    """Raised when a validated feature export is unsuitable for Phase 9."""


@dataclass(frozen=True)
class TabularSplit:
    development_folds: tuple[tuple[tuple[str, ...], str], ...]
    base_training_seasons: tuple[str, ...]
    calibration_season: str
    holdout_seasons: tuple[str, ...]


@dataclass(frozen=True)
class TabularDataset:
    features: NDArray[np.float64]
    targets: NDArray[np.int64]
    match_uuids: tuple[str, ...]
    seasons_by_row: tuple[str, ...]
    kickoffs: tuple[str, ...]
    feature_columns: tuple[str, ...]
    checksum: str
    seasons: tuple[str, ...]
    split: TabularSplit

    def indices_for(self, seasons: tuple[str, ...]) -> NDArray[np.int64]:
        unknown = set(seasons).difference(self.seasons)
        if unknown:
            raise TabularDataContractError(f"unknown seasons: {sorted(unknown)}")
        return np.asarray(
            [index for index, season in enumerate(self.seasons_by_row) if season in seasons],
            dtype=np.int64,
        )

    def matrix_for(self, seasons: tuple[str, ...]) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
        indices = self.indices_for(seasons)
        return self.features[indices], self.targets[indices]


def _standard_split(seasons: tuple[str, ...]) -> TabularSplit:
    if len(seasons) != 6:
        raise TabularDataContractError("Phase 9 requires exactly six chronological seasons")
    return TabularSplit(
        development_folds=(
            ((seasons[0],), seasons[1]),
            ((seasons[0], seasons[1]), seasons[2]),
        ),
        base_training_seasons=seasons[:3],
        calibration_season=seasons[3],
        holdout_seasons=seasons[4:],
    )


def load_tabular_dataset(path: Path) -> TabularDataset:
    """Load only the declared 74 features; identity and target leakage stay excluded."""

    validated = validate_feature_export(path)
    rows: list[list[float]] = []
    targets: list[int] = []
    match_uuids: list[str] = []
    seasons_by_row: list[str] = []
    kickoffs: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            rows.append(
                [
                    float(row[column]) if row[column] else np.nan
                    for column in PREMATCH_FEATURE_COLUMNS
                ]
            )
            result = cast(MatchResult, row["target_result"])
            targets.append(CLASS_ORDER.index(result))
            match_uuids.append(row["match_uuid"])
            seasons_by_row.append(row["season"])
            kickoffs.append(row["kickoff_at"])
    features = np.asarray(rows, dtype=np.float64)
    target_array = np.asarray(targets, dtype=np.int64)
    if features.shape != (validated.row_count, validated.feature_count):
        raise TabularDataContractError("feature matrix shape contradicts the validated contract")
    if not np.isfinite(features[~np.isnan(features)]).all():
        raise TabularDataContractError("feature matrix contains non-finite values")
    if set(np.unique(target_array)) != {0, 1, 2}:
        raise TabularDataContractError("feature export must contain all H/D/A target classes")
    return TabularDataset(
        features=features,
        targets=target_array,
        match_uuids=tuple(match_uuids),
        seasons_by_row=tuple(seasons_by_row),
        kickoffs=tuple(kickoffs),
        feature_columns=PREMATCH_FEATURE_COLUMNS,
        checksum=validated.checksum,
        seasons=validated.seasons,
        split=_standard_split(validated.seasons),
    )
