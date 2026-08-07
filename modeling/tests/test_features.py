"""Time-safe Phase 8 feature calculations."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from prem_engine_modeling.data import HistoricalDataset
from prem_engine_modeling.features import (
    EXPORT_COLUMNS,
    FEATURE_CONTRACT_VERSION,
    PREMATCH_FEATURE_COLUMNS,
    FeaturePipelineConfig,
    build_prematch_features,
)

from .helpers import match_record, six_season_dataset


def test_feature_rows_are_complete_normalized_and_use_24_hour_cutoff() -> None:
    dataset = six_season_dataset()
    output = build_prematch_features(dataset)
    first = output.rows[0]
    values = first.as_flat_dict()

    assert len(output.rows) == len(dataset.records)
    assert tuple(values) == EXPORT_COLUMNS
    assert len(PREMATCH_FEATURE_COLUMNS) == 74
    assert values["feature_contract_version"] == FEATURE_CONTRACT_VERSION
    assert first.feature_cutoff_at == first.match.kickoff_at - timedelta(hours=24)
    assert first.latest_input_available_after is None
    assert first.home.missing_form_last_5 == 1
    assert first.home.missing_rest == 1
    assert sum(
        (
            first.elo_home_probability,
            first.elo_draw_probability,
            first.elo_away_probability,
        )
    ) == pytest.approx(1.0)
    assert sum(
        (
            first.goal_home_probability,
            first.goal_draw_probability,
            first.goal_away_probability,
        )
    ) == pytest.approx(1.0)


def test_result_available_after_snapshot_cannot_change_features() -> None:
    first = match_record(
        identifier="late-result",
        season="2020/21",
        kickoff_at=datetime(2020, 8, 1, 12, tzinfo=UTC),
        home_goals=5,
        away_goals=0,
        available_delay=timedelta(days=3),
    )
    second = match_record(
        identifier="target",
        season="2020/21",
        kickoff_at=datetime(2020, 8, 5, 12, tzinfo=UTC),
        home="Alpha",
        away="Gamma",
    )
    changed_first = replace(first, home_goals=0, away_goals=5, result="A")
    original = HistoricalDataset((first, second), "a" * 64, ("2020/21",))
    changed = HistoricalDataset((changed_first, second), "b" * 64, ("2020/21",))

    original_target = build_prematch_features(original).rows[1]
    changed_target = build_prematch_features(changed).rows[1]

    assert first.available_after == original_target.feature_cutoff_at
    assert original_target.home == changed_target.home
    assert original_target.elo_home_probability == changed_target.elo_home_probability
    assert original_target.goal_expected_home_goals == changed_target.goal_expected_home_goals


def test_simultaneous_result_cannot_leak_and_schedule_features_are_prior_only() -> None:
    kickoff = datetime(2020, 8, 8, 12, tzinfo=UTC)
    earlier = match_record(
        identifier="earlier",
        season="2020/21",
        kickoff_at=kickoff - timedelta(days=7),
        home="Alpha",
        away="Beta",
        home_goals=2,
        away_goals=0,
    )
    simultaneous_one = match_record(
        identifier="sim-one",
        season="2020/21",
        kickoff_at=kickoff,
        home="Alpha",
        away="Gamma",
        home_goals=4,
        away_goals=0,
    )
    simultaneous_two = match_record(
        identifier="sim-two",
        season="2020/21",
        kickoff_at=kickoff,
        home="Delta",
        away="Epsilon",
        home_goals=1,
        away_goals=1,
    )
    dataset = HistoricalDataset(
        (earlier, simultaneous_one, simultaneous_two), "c" * 64, ("2020/21",)
    )
    rows = build_prematch_features(dataset).rows

    assert rows[1].home.rest_days == pytest.approx(7.0)
    assert rows[1].home.matches_last_7_days == 1
    assert rows[2].available_result_count == rows[1].available_result_count


def test_future_outcomes_do_not_change_earlier_feature_rows() -> None:
    dataset = six_season_dataset()
    changed_records = tuple(
        replace(record, home_goals=0, away_goals=7, result="A")
        if record.season == "2025/26"
        else record
        for record in dataset.records
    )
    changed = HistoricalDataset(changed_records, "f" * 64, dataset.seasons)

    original_rows = build_prematch_features(dataset).rows
    changed_rows = build_prematch_features(changed).rows

    for original, modified in zip(original_rows, changed_rows, strict=True):
        if original.match.season != "2025/26":
            original_values = original.as_flat_dict()
            modified_values = modified.as_flat_dict()
            for target in ("target_home_goals", "target_away_goals", "target_result"):
                original_values.pop(target)
                modified_values.pop(target)
            assert original_values == modified_values


def test_promoted_and_history_confidence_features() -> None:
    dataset = six_season_dataset()
    replacement = replace(
        dataset.records[4],
        home_club_uuid=match_record(
            identifier="uuid-source",
            season="2021/22",
            kickoff_at=datetime(2021, 7, 1, tzinfo=UTC),
            home="Epsilon",
        ).home_club_uuid,
        home_club="Epsilon",
    )
    records = dataset.records[:4] + (replacement,) + dataset.records[5:]
    changed = HistoricalDataset(records, "g" * 64, dataset.seasons)
    row = build_prematch_features(changed).rows[4]

    assert row.home.is_promoted == 1
    assert row.home.promotion_status_known == 1
    assert row.home.history_confidence == 0.0


def test_feature_pipeline_requires_positive_lead_time() -> None:
    with pytest.raises(ValueError, match="lead"):
        FeaturePipelineConfig(prediction_lead=timedelta(0))
