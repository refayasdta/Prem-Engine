"""Phase 15 tactical cutoff, coverage, training, and artifact tests."""

from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

import numpy as np
from prem_engine_modeling.data import MatchRecord
from prem_engine_modeling.feature_export import write_feature_export
from prem_engine_modeling.features import build_prematch_features
from prem_engine_modeling.player_data import PERFORMANCE_COLUMNS, load_player_context
from prem_engine_modeling.player_feature_export import write_player_feature_export
from prem_engine_modeling.player_features import build_player_enhanced_features
from prem_engine_modeling.tabular_training import CandidateGrid
from prem_engine_modeling.tactical_artifacts import (
    load_tactical_artifact,
    write_tactical_artifacts,
)
from prem_engine_modeling.tactical_feature_export import (
    human_tactical_feature_report,
    validate_tactical_feature_export,
    write_tactical_feature_export,
)
from prem_engine_modeling.tactical_features import (
    TACTICAL_FEATURE_COLUMNS,
    build_tactical_features,
)
from prem_engine_modeling.tactical_reporting import human_tactical_training_report
from prem_engine_modeling.tactical_training import (
    load_tactical_training_dataset,
    train_tactical_model,
)

from .helpers import match_record, six_season_dataset
from .test_player_context import _context_files, _position, _write_csv

HISTORICAL_COLUMNS = (
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
    "HS",
    "AS",
    "HST",
    "AST",
    "HC",
    "AC",
    "HF",
    "AF",
)


def _write_historical(path: Path, records: list[MatchRecord]) -> None:
    rows = []
    for index, item in enumerate(records):
        rows.append(
            {
                "match_uuid": item.match_uuid,
                "season": item.season,
                "kickoff_at": item.kickoff_at.isoformat(),
                "home_club_uuid": item.home_club_uuid,
                "home_club": item.home_club,
                "away_club_uuid": item.away_club_uuid,
                "away_club": item.away_club,
                "home_goals": item.home_goals,
                "away_goals": item.away_goals,
                "result": item.result,
                "available_after": item.available_after.isoformat(),
                "lagged_history_only": "True",
                "HS": 10,
                "AS": 8,
                "HST": 4,
                "AST": 3 if index else 9,
                "HC": 5,
                "AC": 4,
                "HF": 11,
                "AF": 9,
            }
        )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=HISTORICAL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _tactical_inputs(tmp_path: Path) -> tuple[Path, Path, int]:
    historical = six_season_dataset()
    first = historical.records[0]
    fixtures = (("Alpha", "Beta"), ("Gamma", "Delta"))
    prehistory = []
    for round_index in range(5):
        for fixture_index, (home, away) in enumerate(fixtures):
            prehistory.append(
                match_record(
                    identifier=f"tactical-prehistory-{round_index}-{fixture_index}",
                    season="2019/20",
                    kickoff_at=first.kickoff_at
                    - timedelta(days=70 - round_index * 7)
                    + timedelta(hours=fixture_index),
                    home=home,
                    away=away,
                    home_goals=1,
                    away_goals=0,
                )
            )
    all_historical = sorted(
        prehistory + list(historical.records), key=lambda item: (item.kickoff_at, item.match_uuid)
    )
    historical_path = tmp_path / "historical.csv"
    _write_historical(historical_path, all_historical)

    base = build_prematch_features(historical)
    base_path = tmp_path / "base.csv"
    write_feature_export(base, dataset_path=base_path, report_path=tmp_path / "base.json")
    performance_path, availability_path, transfer_path, _, _ = _context_files(tmp_path)
    performance_rows = list(
        csv.DictReader(performance_path.open("r", encoding="utf-8", newline=""))
    )
    for match in prehistory:
        for club, opponent in (
            (match.home_club_uuid, match.away_club_uuid),
            (match.away_club_uuid, match.home_club_uuid),
        ):
            for index in range(11):
                performance_rows.append(
                    {
                        "match_uuid": match.match_uuid,
                        "season": match.season,
                        "kickoff_at": match.kickoff_at.isoformat(),
                        "available_after": match.available_after.isoformat(),
                        "club_uuid": club,
                        "opponent_club_uuid": opponent,
                        "player_uuid": f"{club}-player-{index:02d}",
                        "position": _position(index),
                        "started": 1,
                        "starting_status_source": "observed",
                        "minutes": 90,
                        "rating": 6.8,
                        "goals": 0,
                        "assists": 0,
                    }
                )
    _write_csv(performance_path, PERFORMANCE_COLUMNS, performance_rows)
    context = load_player_context(
        performances_path=performance_path,
        availability_path=availability_path,
        transfers_path=transfer_path,
    )
    player = build_player_enhanced_features(base_path, context)
    player_path = tmp_path / "player.csv"
    write_player_feature_export(
        player,
        performance_record_count=10_000,
        dataset_path=player_path,
        report_path=tmp_path / "player.json",
    )
    tactical = build_tactical_features(player_path, historical_path, context)
    assert tactical.statistic_anomaly_count == 1
    assert tactical.rows[0].latest_tactical_input_available_after is not None
    assert tactical.rows[0].latest_tactical_input_available_after < first.kickoff_at - timedelta(
        hours=24
    )
    dataset_path = tmp_path / "tactical.csv"
    quality_path = tmp_path / "tactical.json"
    result = write_tactical_feature_export(
        tactical, dataset_path=dataset_path, report_path=quality_path
    )
    assert result.coverage.trainable is True
    assert result.coverage.shape_covered_fixture_rate == 1.0
    assert result.feature_count == 134
    assert "READY FOR MANUAL TRAINING" in human_tactical_feature_report(result)
    return dataset_path, quality_path, tactical.shape_observation_count


def test_tactical_feature_export_and_training_round_trip(tmp_path: Path) -> None:
    dataset_path, quality_path, shape_count = _tactical_inputs(tmp_path)
    validated = validate_tactical_feature_export(dataset_path, shape_observation_count=shape_count)
    assert validated.feature_count == 134
    dataset = load_tactical_training_dataset(dataset_path, quality_path)
    grid = CandidateGrid(
        logistic_c_values=(0.1,),
        boosting_learning_rates=(),
        boosting_leaf_counts=(),
        boosting_l2_values=(),
    )
    result = train_tactical_model(dataset, candidate_grid=grid)
    artifacts = write_tactical_artifacts(result, dataset, artifact_root=tmp_path / "artifacts")
    restored = load_tactical_artifact(artifacts.model_path)
    holdout, _ = dataset.tabular.matrix_for(dataset.tabular.split.holdout_seasons)
    assert np.allclose(restored.predict_proba(holdout), result.holdout_probabilities)
    report = human_tactical_training_report(result, dataset, artifacts)
    assert "PROMOTION VERDICT" in report
    assert "HOW TO READ THIS" in report
    assert len(TACTICAL_FEATURE_COLUMNS) == 34
