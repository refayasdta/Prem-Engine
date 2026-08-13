"""Phase 11 ensemble selection, leakage isolation, artifacts, and scorelines."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from prem_engine_modeling.ensemble_artifacts import (
    load_ensemble_artifact,
    write_ensemble_artifacts,
)
from prem_engine_modeling.ensemble_reporting import human_ensemble_report
from prem_engine_modeling.ensemble_training import (
    COMPONENT_ORDER,
    blend_probabilities,
    candidate_weights,
    reweight_scoreline_matrix,
    train_ensemble_model,
)
from prem_engine_modeling.features import PREMATCH_FEATURE_COLUMNS
from prem_engine_modeling.player_features import PLAYER_FEATURE_COLUMNS
from prem_engine_modeling.tabular_data import TabularDataset, TabularSplit


def _dataset() -> TabularDataset:
    seasons = ("2020/21", "2021/22", "2022/23", "2023/24", "2024/25", "2025/26")
    columns = PREMATCH_FEATURE_COLUMNS + PLAYER_FEATURE_COLUMNS
    rng = np.random.default_rng(42)
    row_count = len(seasons) * 18
    features = rng.normal(size=(row_count, len(columns)))
    targets = np.resize(np.asarray((0, 1, 2), dtype=np.int64), row_count)
    for prefix, values in (
        ("elo", (0.48, 0.27, 0.25)),
        ("goal", (0.50, 0.26, 0.24)),
    ):
        for result, value in zip(("home", "draw", "away"), values, strict=True):
            features[:, columns.index(f"{prefix}_{result}_probability")] = value
    seasons_by_row = tuple(season for season in seasons for _ in range(18))
    return TabularDataset(
        features=np.asarray(features, dtype=np.float64),
        targets=targets,
        match_uuids=tuple(f"match-{index}" for index in range(row_count)),
        seasons_by_row=seasons_by_row,
        kickoffs=tuple(
            f"202{index // 18}-08-{index % 18 + 1:02d}T12:00:00Z" for index in range(row_count)
        ),
        feature_columns=columns,
        checksum="e" * 64,
        seasons=seasons,
        split=TabularSplit(
            development_folds=(((seasons[0],), seasons[1]), (seasons[:2], seasons[2])),
            base_training_seasons=seasons[:3],
            calibration_season=seasons[3],
            holdout_seasons=seasons[4:],
        ),
    )


def test_weight_grid_and_blending_contract() -> None:
    weights = candidate_weights(0.1)
    assert len(weights) == 286
    assert all(sum(candidate) == pytest.approx(1.0) for candidate in weights)
    matrices = {name: np.asarray(((0.5, 0.3, 0.2),), dtype=np.float64) for name in COMPONENT_ORDER}
    assert np.allclose(blend_probabilities(matrices, (0.1, 0.2, 0.3, 0.4)), matrices["elo"])
    with pytest.raises(ValueError, match="sum to one"):
        blend_probabilities(matrices, (0.1, 0.2, 0.3, 0.3))
    with pytest.raises(ValueError, match="divide one"):
        candidate_weights(0.3)


def test_scoreline_reconciliation_preserves_conditional_shapes() -> None:
    original = np.asarray(
        ((0.10, 0.08, 0.02), (0.20, 0.15, 0.05), (0.15, 0.15, 0.10)),
        dtype=np.float64,
    )
    adjusted = reweight_scoreline_matrix(original, (0.55, 0.25, 0.20))
    home = np.tril(adjusted, k=-1).sum()
    draw = np.diag(adjusted).sum()
    away = np.triu(adjusted, k=1).sum()
    assert (home, draw, away) == pytest.approx((0.55, 0.25, 0.20))
    assert adjusted.sum() == pytest.approx(1.0)
    assert adjusted[2, 0] / adjusted[1, 0] == pytest.approx(original[2, 0] / original[1, 0])


def test_holdout_targets_cannot_change_selection_or_predictions() -> None:
    dataset = _dataset()
    changed_targets = dataset.targets.copy()
    holdout_indices = dataset.indices_for(dataset.split.holdout_seasons)
    changed_targets[holdout_indices] = np.resize(np.asarray((2, 0, 1)), len(holdout_indices))
    changed = replace(dataset, targets=changed_targets)

    original = train_ensemble_model(dataset, weight_step=0.25)
    modified = train_ensemble_model(changed, weight_step=0.25)

    assert original.selected == modified.selected
    assert original.calibration_temperature == modified.calibration_temperature
    assert np.array_equal(original.holdout_probabilities, modified.holdout_probabilities)
    assert original.holdout_metrics != modified.holdout_metrics


def test_artifact_restores_predictions_and_human_report(tmp_path: Path) -> None:
    dataset = _dataset()
    result = train_ensemble_model(dataset, weight_step=0.25)
    written = write_ensemble_artifacts(
        result,
        dataset,
        artifact_root=tmp_path / "ensemble",
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    restored = load_ensemble_artifact(written.model_path)
    holdout_features, _ = dataset.matrix_for(dataset.split.holdout_seasons)
    assert np.allclose(restored.predict_proba(holdout_features), result.holdout_probabilities)
    assert restored.promotion_status == result.promotion.status
    with pytest.raises(FileExistsError):
        write_ensemble_artifacts(result, dataset, artifact_root=tmp_path / "ensemble")
    with pytest.raises(ValueError, match="feature contract"):
        restored.predict_proba(holdout_features[:, :-1])
    report = human_ensemble_report(result, dataset, written)
    assert "SELECTED WEIGHTS" in report
    assert "PROMOTION VERDICT" in report
    assert result.promotion.status.upper() in report
