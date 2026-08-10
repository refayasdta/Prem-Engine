"""Phase 10 player contracts, cutoff safety, coverage gates, and artifacts."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from prem_engine_modeling.feature_export import write_feature_export
from prem_engine_modeling.features import build_prematch_features
from prem_engine_modeling.player_artifacts import (
    load_player_artifact,
    write_player_artifacts,
)
from prem_engine_modeling.player_data import (
    AVAILABILITY_COLUMNS,
    PERFORMANCE_COLUMNS,
    TRANSFER_COLUMNS,
    PlayerDataContractError,
    load_player_context,
)
from prem_engine_modeling.player_feature_export import (
    human_player_feature_report,
    write_player_feature_export,
)
from prem_engine_modeling.player_features import build_player_enhanced_features
from prem_engine_modeling.player_reporting import human_player_training_report
from prem_engine_modeling.player_training import (
    InsufficientPlayerCoverageError,
    load_player_impact_dataset,
    train_player_impact_model,
)
from prem_engine_modeling.tabular_training import CandidateGrid

from .helpers import six_season_dataset


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _position(index: int) -> str:
    if index == 0:
        return "goalkeeper"
    if index <= 6:
        return "defender"
    if index <= 12:
        return "midfielder"
    return "attacker"


def _context_files(tmp_path: Path) -> tuple[Path, Path, Path, str, str]:
    historical = six_season_dataset()
    first = historical.records[0]
    clubs = sorted(
        {
            club
            for match in historical.records
            for club in (match.home_club_uuid, match.away_club_uuid)
        }
    )
    performances: list[dict[str, object]] = []
    for club in clubs:
        for player_index in range(18):
            player = f"{club}-player-{player_index:02d}"
            for appearance in range(5):
                kickoff = first.kickoff_at - timedelta(days=60 - appearance * 7)
                performances.append(
                    {
                        "match_uuid": f"preseason-{club}-{player_index}-{appearance}",
                        "season": "2019/20",
                        "kickoff_at": kickoff.isoformat(),
                        "available_after": (kickoff + timedelta(hours=3)).isoformat(),
                        "club_uuid": club,
                        "opponent_club_uuid": "preseason-opponent",
                        "player_uuid": player,
                        "position": _position(player_index),
                        "started": int(
                            player_index == 0
                            or 1 <= player_index <= 4
                            or 7 <= player_index <= 9
                            or 13 <= player_index <= 15
                        ),
                        "minutes": 90 if player_index <= 15 else 25,
                        "rating": 9.0 if player_index == 15 else 6.8,
                        "goals": 1 if player_index == 15 else 0,
                        "assists": 0,
                    }
                )
    for match in historical.records:
        for club, opponent in (
            (match.home_club_uuid, match.away_club_uuid),
            (match.away_club_uuid, match.home_club_uuid),
        ):
            for player_index in range(18):
                performances.append(
                    {
                        "match_uuid": match.match_uuid,
                        "season": match.season,
                        "kickoff_at": match.kickoff_at.isoformat(),
                        "available_after": match.available_after.isoformat(),
                        "club_uuid": club,
                        "opponent_club_uuid": opponent,
                        "player_uuid": f"{club}-player-{player_index:02d}",
                        "position": _position(player_index),
                        "started": int(
                            player_index == 0
                            or 1 <= player_index <= 4
                            or 7 <= player_index <= 9
                            or 13 <= player_index <= 15
                        ),
                        "minutes": 90 if player_index <= 15 else 25,
                        "rating": 9.0 if player_index == 15 else 6.8,
                        "goals": 1 if player_index == 15 else 0,
                        "assists": 0,
                    }
                )
    cutoff = first.kickoff_at - timedelta(hours=24)
    unseen = f"{first.home_club_uuid}-unseen"
    performances.append(
        {
            "match_uuid": "exact-cutoff-performance",
            "season": "2020/21",
            "kickoff_at": (cutoff - timedelta(hours=3)).isoformat(),
            "available_after": cutoff.isoformat(),
            "club_uuid": first.home_club_uuid,
            "opponent_club_uuid": "recent-opponent",
            "player_uuid": unseen,
            "position": "attacker",
            "started": 1,
            "minutes": 90,
            "rating": 10,
            "goals": 5,
            "assists": 0,
        }
    )
    unavailable = f"{first.home_club_uuid}-player-15"
    availability = [
        {
            "target_match_uuid": first.match_uuid,
            "club_uuid": first.home_club_uuid,
            "player_uuid": unavailable,
            "observed_at": (cutoff - timedelta(hours=1)).isoformat(),
            "status": "out",
            "availability_probability": 0,
        }
    ]
    performances_path = tmp_path / "performances.csv"
    availability_path = tmp_path / "availability.csv"
    transfers_path = tmp_path / "transfers.csv"
    _write_csv(performances_path, PERFORMANCE_COLUMNS, performances)
    _write_csv(availability_path, AVAILABILITY_COLUMNS, availability)
    _write_csv(transfers_path, TRANSFER_COLUMNS, [])
    return performances_path, availability_path, transfers_path, unavailable, unseen


def test_player_context_cutoff_features_and_training_round_trip(tmp_path: Path) -> None:
    base = build_prematch_features(six_season_dataset())
    base_path = tmp_path / "base.csv"
    write_feature_export(
        base,
        dataset_path=base_path,
        report_path=tmp_path / "base.json",
    )
    performance_path, availability_path, transfer_path, unavailable, unseen = _context_files(
        tmp_path
    )
    context = load_player_context(
        performances_path=performance_path,
        availability_path=availability_path,
        transfers_path=transfer_path,
    )
    enhanced = build_player_enhanced_features(base_path, context)
    first = enhanced.rows[0]

    assert first.home.candidate_squad_size == 18
    assert first.home.known_absence_count == 1
    assert unavailable not in {player.player_uuid for player in first.home_lineup.starters}
    assert unseen not in {player.player_uuid for player in first.home_lineup.starters}
    assert first.latest_player_input_available_after is not None
    assert first.latest_player_input_available_after < datetime.fromisoformat(
        first.base["feature_cutoff_at"]
    )

    dataset_path = tmp_path / "player-features.csv"
    quality_path = tmp_path / "player-quality.json"
    written = write_player_feature_export(
        enhanced,
        performance_record_count=10_000,
        dataset_path=dataset_path,
        report_path=quality_path,
    )
    assert written.coverage.trainable is True
    assert written.feature_count == 100
    assert "READY FOR TRAINING" in human_player_feature_report(written)

    training_data = load_player_impact_dataset(dataset_path, quality_path)
    grid = CandidateGrid(
        logistic_c_values=(0.1,),
        boosting_learning_rates=(),
        boosting_leaf_counts=(),
        boosting_l2_values=(),
    )
    result = train_player_impact_model(training_data, candidate_grid=grid)
    artifacts = write_player_artifacts(
        result,
        training_data,
        artifact_root=tmp_path / "artifacts",
    )
    restored = load_player_artifact(artifacts.model_path)
    holdout, _ = training_data.tabular.matrix_for(training_data.tabular.split.holdout_seasons)
    assert np.allclose(restored.predict_proba(holdout), result.holdout_probabilities)
    report = human_player_training_report(result, training_data, artifacts)
    assert "PROMOTION VERDICT" in report


def test_player_data_rejects_performance_available_before_kickoff(tmp_path: Path) -> None:
    performance_path, availability_path, transfer_path, _, _ = _context_files(tmp_path)
    rows = list(csv.DictReader(performance_path.open("r", encoding="utf-8", newline="")))
    rows[0]["available_after"] = rows[0]["kickoff_at"]
    kickoff = rows[0]["kickoff_at"]
    rows[0]["available_after"] = (
        datetime.fromisoformat(kickoff) - timedelta(minutes=1)
    ).isoformat()
    _write_csv(performance_path, PERFORMANCE_COLUMNS, rows)

    with pytest.raises(PlayerDataContractError, match="predates kickoff"):
        load_player_context(
            performances_path=performance_path,
            availability_path=availability_path,
            transfers_path=transfer_path,
        )


def test_sparse_player_history_blocks_training_before_fit(tmp_path: Path) -> None:
    base = build_prematch_features(six_season_dataset())
    base_path = tmp_path / "base.csv"
    write_feature_export(
        base,
        dataset_path=base_path,
        report_path=tmp_path / "base.json",
    )
    performance_path = tmp_path / "performances.csv"
    availability_path = tmp_path / "availability.csv"
    transfer_path = tmp_path / "transfers.csv"
    _write_csv(performance_path, PERFORMANCE_COLUMNS, [])
    _write_csv(availability_path, AVAILABILITY_COLUMNS, [])
    _write_csv(transfer_path, TRANSFER_COLUMNS, [])
    context = load_player_context(
        performances_path=performance_path,
        availability_path=availability_path,
        transfers_path=transfer_path,
    )
    enhanced = build_player_enhanced_features(base_path, context)
    dataset_path = tmp_path / "player-features.csv"
    quality_path = tmp_path / "player-quality.json"
    written = write_player_feature_export(
        enhanced,
        performance_record_count=0,
        dataset_path=dataset_path,
        report_path=quality_path,
    )
    assert written.coverage.trainable is False
    assert "TRAINING BLOCKED" in human_player_feature_report(written)
    training_data = load_player_impact_dataset(dataset_path, quality_path)
    with pytest.raises(InsufficientPlayerCoverageError, match="performances"):
        train_player_impact_model(training_data)
