"""Phase 9 selection isolation, calibration, artifacts, and reporting."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from prem_engine_modeling.feature_export import write_feature_export
from prem_engine_modeling.features import build_prematch_features
from prem_engine_modeling.tabular_artifacts import (
    load_tabular_artifact,
    tabular_model_version,
    write_tabular_artifacts,
)
from prem_engine_modeling.tabular_data import TabularDataset, load_tabular_dataset
from prem_engine_modeling.tabular_reporting import human_tabular_report
from prem_engine_modeling.tabular_training import (
    CandidateGrid,
    CandidateSpec,
    build_candidate_pipeline,
    temperature_scale_probabilities,
    train_tabular_model,
)

from .helpers import six_season_dataset

SMALL_GRID = CandidateGrid(
    logistic_c_values=(0.1, 1.0),
    boosting_learning_rates=(0.05,),
    boosting_leaf_counts=(7,),
    boosting_l2_values=(0.1,),
    boosting_iterations=20,
)


def _dataset(tmp_path: Path) -> TabularDataset:
    features = build_prematch_features(six_season_dataset())
    path = tmp_path / "features.csv"
    write_feature_export(
        features,
        dataset_path=path,
        report_path=tmp_path / "features.json",
    )
    return load_tabular_dataset(path)


def test_calibration_and_holdout_targets_cannot_change_candidate_selection(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    changed_targets = dataset.targets.copy()
    changed_indices = dataset.indices_for(
        (dataset.split.calibration_season,) + dataset.split.holdout_seasons
    )
    changed_targets[changed_indices] = np.resize(np.asarray((2, 1, 0)), len(changed_indices))
    changed = replace(dataset, targets=changed_targets)

    original = train_tabular_model(dataset, candidate_grid=SMALL_GRID)
    modified = train_tabular_model(changed, candidate_grid=SMALL_GRID)

    assert original.selected_candidate == modified.selected_candidate
    assert original.leaderboard == modified.leaderboard


def test_holdout_targets_cannot_change_temperature(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    targets = dataset.targets.copy()
    holdout_indices = dataset.indices_for(dataset.split.holdout_seasons)
    targets[holdout_indices] = np.resize(np.asarray((0, 1, 2)), len(holdout_indices))
    changed = replace(dataset, targets=targets)

    original = train_tabular_model(dataset, candidate_grid=SMALL_GRID)
    modified = train_tabular_model(changed, candidate_grid=SMALL_GRID)

    assert original.calibration_temperature == modified.calibration_temperature
    assert np.array_equal(original.holdout_probabilities, modified.holdout_probabilities)
    assert original.holdout_calibrated_metrics != modified.holdout_calibrated_metrics


def test_preprocessing_fits_only_the_supplied_training_matrix() -> None:
    spec = CandidateSpec(
        candidate_id="logistic-test",
        family="multinomial_logistic",
        regularization_c=0.1,
    )
    training = np.asarray(
        ((1.0, np.nan), (2.0, 10.0), (3.0, 20.0), (4.0, 30.0), (5.0, 40.0), (6.0, 50.0))
    )
    targets = np.asarray((0, 1, 2, 0, 1, 2))
    pipeline = build_candidate_pipeline(spec)
    pipeline.fit(training, targets)

    assert pipeline.named_steps["imputer"].statistics_[0] == pytest.approx(3.5)
    assert pipeline.named_steps["imputer"].statistics_[1] == pytest.approx(30.0)


def test_training_is_deterministic_and_artifact_restores_probabilities(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    first = train_tabular_model(dataset, candidate_grid=SMALL_GRID)
    second = train_tabular_model(dataset, candidate_grid=SMALL_GRID)

    assert first.selected_candidate == second.selected_candidate
    assert first.calibration_temperature == second.calibration_temperature
    assert np.array_equal(first.holdout_probabilities, second.holdout_probabilities)
    assert np.allclose(first.holdout_probabilities.sum(axis=1), 1.0)

    written = write_tabular_artifacts(
        first,
        dataset,
        artifact_root=tmp_path / "artifacts",
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    restored = load_tabular_artifact(written.model_path)
    holdout_features, _ = dataset.matrix_for(dataset.split.holdout_seasons)
    restored_probabilities = restored.predict_proba(holdout_features)
    assert np.allclose(restored_probabilities, first.holdout_probabilities)
    assert restored.promotion_status == first.promotion.status
    assert written.model_version == tabular_model_version(
        dataset,
        first.selected_candidate,
        temperature=first.calibration_temperature,
    )
    with pytest.raises(FileExistsError):
        write_tabular_artifacts(first, dataset, artifact_root=tmp_path / "artifacts")
    with pytest.raises(ValueError, match="feature contract"):
        restored.predict_proba(holdout_features[:, :-1])

    report = human_tabular_report(first, dataset, written)
    assert "CANDIDATE LEADERBOARD" in report
    assert "PROMOTION VERDICT" in report
    assert first.promotion.status.upper() in report


def test_temperature_validation_and_candidate_contracts() -> None:
    probabilities = np.asarray(((0.6, 0.3, 0.1), (0.2, 0.3, 0.5)), dtype=np.float64)
    pipeline_spec = CandidateSpec("incomplete", "multinomial_logistic")
    with pytest.raises(ValueError, match="regularization"):
        build_candidate_pipeline(pipeline_spec)
    with pytest.raises(ValueError, match="temperature"):
        temperature_scale_probabilities(probabilities, 0.0)
