"""Input provenance and chronological split tests."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from prem_engine_modeling.data import (
    DatasetContractError,
    load_historical_dataset,
    standard_six_season_split,
)

from .helpers import six_season_dataset


def write_export(
    path: Path,
    *,
    result: str = "H",
    available_after: str = "2020-08-01T16:00:00+00:00",
) -> None:
    columns = (
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
    )
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "match_uuid": "6f311521-6158-51e3-b003-9fdebfd22686",
                "season": "2020/21",
                "kickoff_at": "2020-08-01T12:00:00+00:00",
                "home_club_uuid": "f95f243e-49f5-5f50-8290-136eda03c41d",
                "home_club": "Alpha",
                "away_club_uuid": "a343a557-437b-564d-94bb-978664648adb",
                "away_club": "Beta",
                "home_goals": "2",
                "away_goals": "0",
                "result": result,
                "available_after": available_after,
                "lagged_history_only": "True",
            }
        )


def test_loader_accepts_time_safe_export_and_hashes_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "matches.csv"
    write_export(path)

    dataset = load_historical_dataset(path)

    assert len(dataset.records) == 1
    assert dataset.records[0].home_club == "Alpha"
    assert len(dataset.checksum) == 64


@pytest.mark.parametrize(
    ("result", "available_after", "message"),
    [
        ("A", "2020-08-01T16:00:00+00:00", "contradicts"),
        ("H", "2020-08-01T12:00:00+00:00", "available after kickoff"),
    ],
)
def test_loader_rejects_leaky_or_contradictory_rows(
    tmp_path: Path, result: str, available_after: str, message: str
) -> None:
    path = tmp_path / "invalid.csv"
    write_export(path, result=result, available_after=available_after)

    with pytest.raises(DatasetContractError, match=message):
        load_historical_dataset(path)


def test_standard_split_keeps_last_two_seasons_as_holdouts() -> None:
    dataset = six_season_dataset()

    split = standard_six_season_split(dataset)
    prefix = dataset.through_season(split.validation_season)

    assert split.history_seasons == ("2020/21", "2021/22", "2022/23")
    assert split.validation_season == "2023/24"
    assert split.test_seasons == ("2024/25", "2025/26")
    assert prefix.seasons == dataset.seasons[:4]
    assert all(record.season not in split.test_seasons for record in prefix.records)
