"""Phase 12 statistics contracts, leakage isolation, artifacts, and reporting."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from prem_engine_modeling.features import PREMATCH_FEATURE_COLUMNS
from prem_engine_modeling.match_statistics_artifacts import (
    load_statistics_artifact,
    write_statistics_artifacts,
)
from prem_engine_modeling.match_statistics_data import (
    STATISTIC_TARGETS,
    DetailedStatisticsDataset,
)
from prem_engine_modeling.match_statistics_reporting import human_statistics_report
from prem_engine_modeling.match_statistics_training import (
    CountModelGrid,
    reconcile_statistic_means,
    train_detailed_statistics_models,
)
from prem_engine_modeling.tabular_data import TabularDataset, TabularSplit


def _dataset() -> DetailedStatisticsDataset:
    seasons = ("2020/21", "2021/22", "2022/23", "2023/24", "2024/25", "2025/26")
    rows_per_season = 18
    row_count = len(seasons) * rows_per_season
    rng = np.random.default_rng(42)
    features = rng.normal(size=(row_count, len(PREMATCH_FEATURE_COLUMNS)))
    result_targets = np.resize(np.asarray((0, 1, 2), dtype=np.int64), row_count)
    statistic_columns: list[NDArray[np.int64]] = []
    family_rates = {
        "half_time_goals": 0.7,
        "shots": 12.0,
        "shots_on_target": 4.0,
        "corners": 5.0,
        "fouls": 10.0,
        "yellow_cards": 2.0,
        "red_cards": 0.08,
    }
    for index, target in enumerate(STATISTIC_TARGETS):
        rate = family_rates[target.family] * np.exp(0.08 * features[:, index])
        statistic_columns.append(rng.poisson(rate))
    statistics = np.column_stack(statistic_columns).astype(np.float64)
    seasons_by_row = tuple(season for season in seasons for _ in range(rows_per_season))
    tabular = TabularDataset(
        features=np.asarray(features, dtype=np.float64),
        targets=result_targets,
        match_uuids=tuple(f"match-{index}" for index in range(row_count)),
        seasons_by_row=seasons_by_row,
        kickoffs=tuple(f"kickoff-{index}" for index in range(row_count)),
        feature_columns=PREMATCH_FEATURE_COLUMNS,
        checksum="f" * 64,
        seasons=seasons,
        split=TabularSplit(
            development_folds=(((seasons[0],), seasons[1]), (seasons[:2], seasons[2])),
            base_training_seasons=seasons[:3],
            calibration_season=seasons[3],
            holdout_seasons=seasons[4:],
        ),
    )
    return DetailedStatisticsDataset(
        tabular=tabular,
        targets=statistics,
        target_specs=STATISTIC_TARGETS,
        statistics_checksum="a" * 64,
    )


def test_reconciliation_caps_shots_on_target() -> None:
    values = np.ones((1, len(STATISTIC_TARGETS)), dtype=np.float64)
    positions = {target.name: index for index, target in enumerate(STATISTIC_TARGETS)}
    values[0, positions["home_shots"]] = 4.0
    values[0, positions["home_shots_on_target"]] = 7.0
    adjusted = reconcile_statistic_means(values, STATISTIC_TARGETS)
    assert adjusted[0, positions["home_shots_on_target"]] == 4.0
    with pytest.raises(ValueError, match="target contract"):
        reconcile_statistic_means(values[:, :-1], STATISTIC_TARGETS)


def test_holdout_targets_cannot_change_fitting_or_raw_predictions() -> None:
    dataset = _dataset()
    grid = CountModelGrid(alpha_values=(1.0,))
    changed_targets = dataset.targets.copy()
    holdout = dataset.tabular.indices_for(dataset.tabular.split.holdout_seasons)
    changed_targets[holdout] = np.flip(changed_targets[holdout], axis=0) + 1.0
    changed = replace(dataset, targets=changed_targets)

    original = train_detailed_statistics_models(dataset, grid=grid)
    modified = train_detailed_statistics_models(changed, grid=grid)

    for first, second in zip(original.targets, modified.targets, strict=True):
        assert first.selected_alpha == second.selected_alpha
        assert first.calibration_multiplier == second.calibration_multiplier
        assert first.residual_quantile_90 == second.residual_quantile_90
        assert np.array_equal(first.holdout_predictions, second.holdout_predictions)


def test_artifact_round_trip_and_human_report(tmp_path: Path) -> None:
    dataset = _dataset()
    result = train_detailed_statistics_models(
        dataset, grid=CountModelGrid(alpha_values=(1.0,))
    )
    written = write_statistics_artifacts(
        result,
        dataset,
        artifact_root=tmp_path / "statistics",
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    predictor = load_statistics_artifact(written.model_path)
    features, _ = dataset.tabular.matrix_for(dataset.tabular.split.holdout_seasons)
    restored = predictor.predict(features)
    restored_matrix = np.asarray(
        [[prediction.means[target.name] for target in STATISTIC_TARGETS] for prediction in restored]
    )
    assert np.allclose(restored_matrix, result.official_holdout_predictions)
    assert all(
        lower >= 0.0 and upper >= lower
        for prediction in restored
        for lower, upper in prediction.intervals_90.values()
    )
    with pytest.raises(FileExistsError):
        write_statistics_artifacts(result, dataset, artifact_root=tmp_path / "statistics")
    with pytest.raises(ValueError, match="feature contract"):
        predictor.predict(features[:, :-1])
    report = human_statistics_report(result, dataset, written)
    assert "HOLDOUT TARGET DECISIONS" in report
    assert "UNSUPPORTED HISTORICAL TARGETS" in report
