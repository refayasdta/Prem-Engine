"""Deterministic feature exports and human quality reports."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from prem_engine_modeling.feature_export import (
    FeatureExportContractError,
    feature_quality_summary,
    human_feature_report,
    render_feature_csv,
    validate_feature_export,
    write_feature_export,
)
from prem_engine_modeling.features import build_prematch_features

from .helpers import six_season_dataset


def test_feature_csv_and_summary_are_deterministic(tmp_path: Path) -> None:
    dataset = build_prematch_features(six_season_dataset())
    first_body = render_feature_csv(dataset)
    second_body = render_feature_csv(dataset)
    assert first_body == second_body
    assert first_body.count(b"\n") == len(dataset.rows) + 1

    written = write_feature_export(
        dataset,
        dataset_path=tmp_path / "features.csv",
        report_path=tmp_path / "features.report.json",
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
    )
    summary = feature_quality_summary(dataset, dataset_checksum=written.dataset_checksum)
    assert written.row_count == 24
    assert written.feature_count == 74
    assert len(written.dataset_checksum) == 64
    assert summary["cutoff_violation_count"] == 0
    assert summary["prediction_lead_hours"] == 24
    assert summary["rows_by_season"] == {season: 4 for season in dataset.seasons}
    validated = validate_feature_export(written.dataset_path)
    assert validated.checksum == written.dataset_checksum
    assert validated.row_count == written.row_count
    assert validated.feature_count == written.feature_count

    report = human_feature_report(dataset, written)
    assert "FEATURE EXPORT COMPLETED SUCCESSFULLY" in report
    assert "Cutoff violations        0" in report
    assert "Missing early history" in report

    with pytest.raises(FileExistsError, match="--force"):
        write_feature_export(
            dataset,
            dataset_path=written.dataset_path,
            report_path=written.report_path,
        )


def test_force_replaces_existing_export(tmp_path: Path) -> None:
    dataset = build_prematch_features(six_season_dataset())
    output = tmp_path / "features.csv"
    report = tmp_path / "report.json"
    first = write_feature_export(dataset, dataset_path=output, report_path=report)
    second = write_feature_export(
        dataset,
        dataset_path=output,
        report_path=report,
        force=True,
    )
    assert first.dataset_checksum == second.dataset_checksum


def test_feature_validator_rejects_schema_and_cutoff_leakage(tmp_path: Path) -> None:
    dataset = build_prematch_features(six_season_dataset())
    body = render_feature_csv(dataset).decode("utf-8")
    bad_schema = tmp_path / "bad-schema.csv"
    bad_schema.write_text(body.replace("home_elo_rating", "unexpected_rating", 1), encoding="utf-8")
    with pytest.raises(FeatureExportContractError, match="columns"):
        validate_feature_export(bad_schema)

    bad_cutoff = tmp_path / "bad-cutoff.csv"
    lines = body.splitlines()
    values = lines[1].split(",")
    values[5] = "12"
    lines[1] = ",".join(values)
    bad_cutoff.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(FeatureExportContractError, match="24 hours"):
        validate_feature_export(bad_cutoff)
