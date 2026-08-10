"""Phase 12 detailed match-statistics dataset contract."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from prem_engine_modeling.tabular_data import TabularDataset, load_tabular_dataset

Side = Literal["home", "away"]


@dataclass(frozen=True, order=True)
class StatisticTarget:
    family: str
    side: Side
    source_column: str

    @property
    def name(self) -> str:
        return f"{self.side}_{self.family}"


STATISTIC_TARGETS: tuple[StatisticTarget, ...] = (
    StatisticTarget("half_time_goals", "home", "half_time_home_goals"),
    StatisticTarget("half_time_goals", "away", "half_time_away_goals"),
    StatisticTarget("shots", "home", "HS"),
    StatisticTarget("shots", "away", "AS"),
    StatisticTarget("shots_on_target", "home", "HST"),
    StatisticTarget("shots_on_target", "away", "AST"),
    StatisticTarget("corners", "home", "HC"),
    StatisticTarget("corners", "away", "AC"),
    StatisticTarget("fouls", "home", "HF"),
    StatisticTarget("fouls", "away", "AF"),
    StatisticTarget("yellow_cards", "home", "HY"),
    StatisticTarget("yellow_cards", "away", "AY"),
    StatisticTarget("red_cards", "home", "HR"),
    StatisticTarget("red_cards", "away", "AR"),
)

UNSUPPORTED_TARGETS: dict[str, str] = {
    "possession": "The six-season historical match export has no possession labels.",
    "provider_expected_goals": (
        "The six-season historical match export has no provider-measured expected-goals labels."
    ),
}


class StatisticsDataContractError(ValueError):
    """Raised when statistics and pre-match features do not describe the same fixtures."""


@dataclass(frozen=True)
class DetailedStatisticsDataset:
    tabular: TabularDataset
    targets: NDArray[np.float64]
    target_specs: tuple[StatisticTarget, ...]
    statistics_checksum: str

    def targets_for(self, seasons: tuple[str, ...]) -> NDArray[np.float64]:
        return self.targets[self.tabular.indices_for(seasons)]


def _read_statistics(path: Path) -> tuple[dict[str, dict[str, str]], str]:
    body = path.read_bytes()
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"match_uuid", "season"}.union(
            target.source_column for target in STATISTIC_TARGETS
        )
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise StatisticsDataContractError(
                f"historical statistics export is missing columns: {sorted(missing)}"
            )
        for row in reader:
            match_uuid = row["match_uuid"]
            if not match_uuid or match_uuid in rows:
                raise StatisticsDataContractError(
                    "historical statistics export has a blank or duplicate match UUID"
                )
            rows[match_uuid] = row
    return rows, hashlib.sha256(body).hexdigest()


def load_detailed_statistics_dataset(
    feature_path: Path,
    historical_path: Path,
) -> DetailedStatisticsDataset:
    tabular = load_tabular_dataset(feature_path)
    statistics, checksum = _read_statistics(historical_path)
    if set(statistics) != set(tabular.match_uuids):
        missing = set(tabular.match_uuids).difference(statistics)
        extra = set(statistics).difference(tabular.match_uuids)
        raise StatisticsDataContractError(
            f"fixture identity mismatch: missing={len(missing)}, extra={len(extra)}"
        )
    values: list[list[float]] = []
    for match_uuid, expected_season in zip(
        tabular.match_uuids, tabular.seasons_by_row, strict=True
    ):
        row = statistics[match_uuid]
        if row["season"] != expected_season:
            raise StatisticsDataContractError("fixture season differs between source contracts")
        target_values: list[float] = []
        for target in STATISTIC_TARGETS:
            raw = row[target.source_column]
            if raw == "":
                raise StatisticsDataContractError(f"{target.source_column} contains missing data")
            value = float(raw)
            if not np.isfinite(value) or value < 0.0 or not value.is_integer():
                raise StatisticsDataContractError(
                    f"{target.source_column} must contain non-negative integer counts"
                )
            target_values.append(value)
        values.append(target_values)
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.shape != (len(tabular.targets), len(STATISTIC_TARGETS)):
        raise StatisticsDataContractError("statistics target matrix has an invalid shape")
    return DetailedStatisticsDataset(
        tabular=tabular,
        targets=matrix,
        target_specs=STATISTIC_TARGETS,
        statistics_checksum=checksum,
    )
