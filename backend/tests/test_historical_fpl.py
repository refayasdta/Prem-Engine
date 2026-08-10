from __future__ import annotations

import httpx
import pytest
from prem_engine_api.config import Settings
from prem_engine_api.providers.historical_fpl.audit import (
    POTENTIAL_SAME_FIXTURE_LEAKAGE_COLUMNS,
    ParsedCsv,
    audit_season,
    parse_csv,
    summarize_audit,
)
from prem_engine_api.providers.historical_fpl.client import (
    HistoricalFplClient,
    HistoricalFplDownloadBudgetError,
)
from prem_engine_api.providers.raw_storage import LocalRawResponseStore


def test_season_audit_counts_performances_mapping_and_leakage() -> None:
    columns = (
        "element",
        "fixture",
        "kickoff_time",
        "minutes",
        "team",
        "position",
        "goals_scored",
        "assists",
        "xP",
    )
    rows = []
    for index in range(30):
        rows.append(
            {
                "element": str(index + 1),
                "fixture": "10",
                "kickoff_time": "2024-01-01T15:00:00Z",
                "minutes": "90" if index < 22 else "0",
                "team": "home" if index < 15 else "away",
                "position": "MID",
                "goals_scored": "0",
                "assists": "0",
                "xP": "2.0",
            }
        )
    players = ParsedCsv(
        columns=("id", "code"),
        rows=tuple({"id": str(index + 1), "code": str(1000 + index)} for index in range(30)),
    )
    fixtures = ParsedCsv(columns=("id",), rows=({"id": "10"},))

    result = audit_season(
        season="2024-25",
        merged=ParsedCsv(columns=columns, rows=tuple(rows)),
        players=players,
        fixtures=fixtures,
    )

    assert result["fixture_count"] == 1
    assert result["unique_player_fixture_performance_count"] == 22
    assert result["candidate_covered_fixture_rate"] == 1.0
    assert result["participant_covered_fixture_rate"] == 1.0
    assert result["player_identity_mapping_rate"] == 1.0
    assert result["potential_same_fixture_leakage_columns_present"] == ["xP"]
    assert "xP" in POTENTIAL_SAME_FIXTURE_LEAKAGE_COLUMNS


def test_summary_applies_phase_10_training_gates() -> None:
    season = {
        "available": True,
        "unique_player_fixture_performance_count": 12_000,
        "fixture_count": 1_900,
        "candidate_covered_fixture_count": 1_800,
        "required_columns_missing": [],
        "player_identity_mapping_rate": 1.0,
    }

    summary = summarize_audit([season], target_fixture_count=2_280)

    assert summary["performance_gate_passes"] is True
    assert summary["coverage_gate_passes"] is True
    assert summary["player_strength_source_ready"] is True
    assert summary["full_availability_model_ready"] is False


def test_csv_parser_handles_bom_and_empty_values() -> None:
    parsed = parse_csv("\ufeffid,name\n1,\n".encode())

    assert parsed.columns == ("id", "name")
    assert parsed.rows == ({"id": "1", "name": ""},)


@pytest.mark.asyncio
async def test_client_captures_public_csv_and_enforces_ceiling(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"].startswith("Prem-Engine")
        return httpx.Response(200, content=b"id,value\n1,2\n")

    async with HistoricalFplClient(
        settings=Settings(),
        raw_store=LocalRawResponseStore(tmp_path),
        max_downloads=1,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.get_csv("/2024-25/fixtures.csv")
        assert response.status_code == 200
        assert (tmp_path / response.raw_object_key).is_file()
        with pytest.raises(HistoricalFplDownloadBudgetError):
            await client.get_csv("/2024-25/players_raw.csv")
