"""Strict Phase 9 feature-matrix loading."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from prem_engine_modeling.feature_export import write_feature_export
from prem_engine_modeling.features import PREMATCH_FEATURE_COLUMNS, build_prematch_features
from prem_engine_modeling.tabular_data import TabularDataContractError, load_tabular_dataset

from .helpers import six_season_dataset


def _export(tmp_path: Path) -> Path:
    features = build_prematch_features(six_season_dataset())
    path = tmp_path / "features.csv"
    write_feature_export(
        features,
        dataset_path=path,
        report_path=tmp_path / "report.json",
    )
    return path


def test_loader_selects_only_approved_features_and_builds_split(tmp_path: Path) -> None:
    dataset = load_tabular_dataset(_export(tmp_path))

    assert dataset.features.shape == (24, 74)
    assert dataset.targets.shape == (24,)
    assert dataset.feature_columns == PREMATCH_FEATURE_COLUMNS
    assert not any("target" in column or "uuid" in column for column in dataset.feature_columns)
    assert dataset.split.base_training_seasons == ("2020/21", "2021/22", "2022/23")
    assert dataset.split.calibration_season == "2023/24"
    assert dataset.split.holdout_seasons == ("2024/25", "2025/26")
    assert len(dataset.indices_for(("2024/25",))) == 4
    assert np.isnan(dataset.features).any()


def test_unknown_season_is_rejected(tmp_path: Path) -> None:
    dataset = load_tabular_dataset(_export(tmp_path))
    with pytest.raises(TabularDataContractError, match="unknown"):
        dataset.indices_for(("2030/31",))


def test_phase_9_requires_all_six_seasons(tmp_path: Path) -> None:
    dataset = build_prematch_features(six_season_dataset())
    shortened = replace(dataset, rows=dataset.rows[:20], seasons=dataset.seasons[:5])
    path = tmp_path / "short.csv"
    write_feature_export(
        shortened,
        dataset_path=path,
        report_path=tmp_path / "short.json",
    )
    with pytest.raises(TabularDataContractError, match="six"):
        load_tabular_dataset(path)
