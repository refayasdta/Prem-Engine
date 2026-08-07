"""Historical CSV contract, mapping, and download boundary tests."""

from datetime import date, time
from pathlib import Path

import httpx
import pytest
from prem_engine_api.historical.client import FootballDataClient, season_segment, source_url
from prem_engine_api.historical.contracts import HistoricalDataError, parse_historical_csv
from prem_engine_api.historical.mapping import load_reviewed_aliases, normalize_club_alias

VALID_CSV = (
    b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,"
    b"HS,AS,B365H,B365D,B365A\r\n"
    b"E0,12/09/2020,12:30,Fulham,Arsenal,0,3,A,0,1,A,5,13,6.00,4.33,1.53\r\n"
)


def test_historical_csv_parses_and_fingerprints_source_rows() -> None:
    parsed = parse_historical_csv(VALID_CSV)

    assert len(parsed.schema_fingerprint) == 64
    assert len(parsed.rows) == 1
    row = parsed.rows[0]
    assert row.source_row_number == 2
    assert row.match_date == date(2020, 9, 12)
    assert row.match_time == time(12, 30)
    assert row.full_time_result == "A"
    assert row.statistics == {"HS": 5, "AS": 13}
    assert row.benchmark_odds["B365A"] == 1.53
    assert len(row.row_checksum) == 64


def test_historical_csv_rejects_contradictory_results() -> None:
    body = VALID_CSV.replace(b",0,3,A,", b",0,3,H,")

    with pytest.raises(HistoricalDataError, match="contradicts"):
        parse_historical_csv(body)


def test_historical_csv_rejects_missing_contract_columns() -> None:
    with pytest.raises(HistoricalDataError, match="missing required columns"):
        parse_historical_csv(b"Date,HomeTeam,AwayTeam\n12/09/20,Fulham,Arsenal\n")


def test_reviewed_alias_registry_has_unique_stable_keys() -> None:
    registry = Path("data/mappings/football-data-clubs.csv")
    aliases = load_reviewed_aliases(registry)

    assert len(aliases) >= 50
    assert normalize_club_alias("Nott'm Forest") == "nottmforest"
    assert normalize_club_alias("Brighton & Hove Albion") == "brightonhovealbion"


@pytest.mark.asyncio
async def test_football_data_client_uses_bounded_season_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://source.test/mmz4281/2021/E0.csv"
        return httpx.Response(200, content=VALID_CSV, headers={"content-type": "text/csv"})

    client = FootballDataClient(
        base_url="https://source.test/mmz4281",
        transport=httpx.MockTransport(handler),
    )
    download = await client.download_season(2020)

    assert download.body == VALID_CSV
    assert season_segment(2025) == "2526"
    assert source_url("https://source.test/mmz4281/", 2025).endswith("/2526/E0.csv")
