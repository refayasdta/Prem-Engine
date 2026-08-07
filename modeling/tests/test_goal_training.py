"""Phase 7 leakage, tuning isolation, determinism, and artifact tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from prem_engine_modeling.data import HistoricalDataset
from prem_engine_modeling.goal_artifacts import (
    goal_model_version,
    load_goal_artifact,
    write_goal_artifacts,
)
from prem_engine_modeling.goal_reporting import human_training_report
from prem_engine_modeling.goal_training import (
    GoalParameterGrid,
    train_goal_model,
    walk_forward_goals,
)
from prem_engine_modeling.goals import GoalModelConfig
from prem_engine_modeling.training import ParameterGrid, train_baseline

from .helpers import club_uuid, match_record, six_season_dataset

SMALL_GOAL_GRID = GoalParameterGrid(
    learning_rates=(0.02, 0.06),
    base_goal_rates=(1.25, 1.45),
    home_advantages=(0.18,),
    dixon_coles_rhos=(-0.08,),
    season_carryovers=(0.9,),
)
SMALL_ELO_GRID = ParameterGrid(
    k_factors=(20.0,),
    home_advantages=(80.0,),
    draw_propensities=(0.65,),
    margin_weights=(0.5,),
    season_carryovers=(0.95,),
)


def _train(dataset: HistoricalDataset):  # type: ignore[no-untyped-def]
    elo = train_baseline(dataset, parameter_grid=SMALL_ELO_GRID)
    return train_goal_model(dataset, parameter_grid=SMALL_GOAL_GRID, elo_result=elo)


def test_unavailable_result_cannot_change_overlapping_goal_prediction() -> None:
    first = match_record(
        identifier="first-goals",
        season="2020/21",
        kickoff_at=datetime(2020, 8, 1, 12, tzinfo=UTC),
        home_goals=5,
        away_goals=0,
        available_delay=timedelta(hours=5),
    )
    second = match_record(
        identifier="second-goals",
        season="2020/21",
        kickoff_at=datetime(2020, 8, 1, 15, tzinfo=UTC),
        home="Alpha",
        away="Gamma",
    )
    changed_first = replace(first, home_goals=0, away_goals=5, result="A")
    original = HistoricalDataset((first, second), "a" * 64, ("2020/21",))
    changed = HistoricalDataset((changed_first, second), "b" * 64, ("2020/21",))

    original_output = walk_forward_goals(
        original, config=GoalModelConfig(), score_seasons=("2020/21",)
    )
    changed_output = walk_forward_goals(
        changed, config=GoalModelConfig(), score_seasons=("2020/21",)
    )

    assert original_output.predictions[1].forecast == changed_output.predictions[1].forecast
    assert original_output.final_attack != changed_output.final_attack


def test_holdout_outcomes_cannot_change_goal_parameter_selection() -> None:
    dataset = six_season_dataset()
    changed_records = tuple(
        replace(record, home_goals=0, away_goals=5, result="A")
        if record.season in ("2024/25", "2025/26")
        else record
        for record in dataset.records
    )
    changed = HistoricalDataset(changed_records, "e" * 64, dataset.seasons)

    original_result = _train(dataset)
    changed_result = _train(changed)

    assert original_result.tuning.selected_config == changed_result.tuning.selected_config
    assert original_result.tuning.validation_metrics == changed_result.tuning.validation_metrics
    assert original_result.holdout_metrics != changed_result.holdout_metrics


def test_goal_training_and_artifacts_are_reproducible(tmp_path: Path) -> None:
    dataset = six_season_dataset()
    first = _train(dataset)
    second = _train(dataset)
    assert first.tuning == second.tuning
    assert first.test_predictions == second.test_predictions
    assert first.final_attack == second.final_attack
    assert first.tuning.candidate_count == 4

    written = write_goal_artifacts(
        first,
        dataset,
        artifact_root=tmp_path,
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
    )
    restored = load_goal_artifact(written.model_path)
    assert written.model_version == goal_model_version(dataset, first.tuning.selected_config)
    assert restored.attack_snapshot()[club_uuid("Alpha")] == pytest.approx(
        first.final_attack[club_uuid("Alpha")]
    )
    assert sum(
        restored.predict(club_uuid("Alpha"), club_uuid("Beta")).outcome_probabilities.as_tuple()
    ) == pytest.approx(1.0)
    with pytest.raises(FileExistsError):
        write_goal_artifacts(first, dataset, artifact_root=tmp_path)

    report = human_training_report(first, dataset, written)
    assert "TRAINING COMPLETED SUCCESSFULLY" in report
    assert "PLAIN-LANGUAGE RESULT" in report
    assert "Lower Goal MAE" in report
