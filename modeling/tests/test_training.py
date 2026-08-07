"""Walk-forward leakage, tuning isolation, and artifact tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from prem_engine_modeling.artifacts import (
    load_elo_artifact,
    model_version,
    write_training_artifacts,
)
from prem_engine_modeling.data import HistoricalDataset
from prem_engine_modeling.elo import EloConfig
from prem_engine_modeling.training import ParameterGrid, train_baseline, walk_forward

from .helpers import club_uuid, match_record, six_season_dataset

SMALL_GRID = ParameterGrid(
    k_factors=(12.0, 24.0),
    home_advantages=(40.0, 80.0),
    draw_propensities=(0.55, 0.75),
    margin_weights=(0.0,),
    season_carryovers=(0.85,),
)


def test_unavailable_result_cannot_change_a_later_overlapping_prediction() -> None:
    first = match_record(
        identifier="first",
        season="2020/21",
        kickoff_at=datetime(2020, 8, 1, 12, tzinfo=UTC),
        home="Alpha",
        away="Beta",
        home_goals=4,
        away_goals=0,
        available_delay=timedelta(hours=5),
    )
    second = match_record(
        identifier="second",
        season="2020/21",
        kickoff_at=datetime(2020, 8, 1, 15, tzinfo=UTC),
        home="Alpha",
        away="Gamma",
        home_goals=1,
        away_goals=0,
    )
    changed_first = replace(first, home_goals=0, away_goals=4, result="A")
    original = HistoricalDataset((first, second), "a" * 64, ("2020/21",))
    changed = HistoricalDataset((changed_first, second), "b" * 64, ("2020/21",))

    original_output = walk_forward(original, config=EloConfig(), score_seasons=("2020/21",))
    changed_output = walk_forward(changed, config=EloConfig(), score_seasons=("2020/21",))

    original_probabilities = original_output.predictions[1].probabilities
    changed_probabilities = changed_output.predictions[1].probabilities
    assert original_probabilities == changed_probabilities
    assert original_output.final_ratings != changed_output.final_ratings


def test_test_outcomes_cannot_change_validation_parameter_selection() -> None:
    dataset = six_season_dataset()
    changed_records = tuple(
        replace(record, home_goals=0, away_goals=5, result="A")
        if record.season in ("2024/25", "2025/26")
        else record
        for record in dataset.records
    )
    changed = HistoricalDataset(changed_records, "e" * 64, dataset.seasons)

    original_result = train_baseline(dataset, parameter_grid=SMALL_GRID)
    changed_result = train_baseline(changed, parameter_grid=SMALL_GRID)

    assert original_result.tuning.selected_config == changed_result.tuning.selected_config
    assert (
        original_result.tuning.validation_metrics.log_loss
        == changed_result.tuning.validation_metrics.log_loss
    )
    assert original_result.elo_test_metrics.log_loss != changed_result.elo_test_metrics.log_loss


def test_training_is_reproducible_and_artifact_restores_predictions(tmp_path: Path) -> None:
    dataset = six_season_dataset()
    first = train_baseline(dataset, parameter_grid=SMALL_GRID)
    second = train_baseline(dataset, parameter_grid=SMALL_GRID)

    assert first.tuning == second.tuning
    assert first.test_predictions == second.test_predictions
    assert first.final_ratings == second.final_ratings
    assert first.tuning.candidate_count == 8

    written = write_training_artifacts(
        first,
        dataset,
        artifact_root=tmp_path,
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
    )
    restored = load_elo_artifact(written.model_path)

    assert written.model_version == model_version(dataset, first.tuning.selected_config)
    assert len(written.model_checksum) == 64
    assert restored.rating(club_uuid("Alpha")) == pytest.approx(
        first.final_ratings[club_uuid("Alpha")]
    )
    assert sum(restored.predict(club_uuid("Alpha"), club_uuid("Beta")).as_tuple()) == pytest.approx(
        1.0
    )
    with pytest.raises(FileExistsError):
        write_training_artifacts(first, dataset, artifact_root=tmp_path)
