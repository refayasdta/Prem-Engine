"""Pure scheduling and provider-pagination contracts for local synchronization."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from prem_engine_api.ingestion.fixtures import (
    matchweek_from_round,
    select_canonical_provider_fixtures,
)
from prem_engine_api.local_sync import active_season_start_year, next_cursor
from prem_engine_api.providers.kickoffapi.contracts import FixtureEnvelope


@pytest.mark.parametrize(
    ("label", "expected"),
    (
        ("Matchday 1", 1),
        ("Matchweek 24", 24),
        ("Round - 38", 38),
        ("Regular Season", None),
        ("Matchday 0", None),
        (None, None),
    ),
)
def test_explicit_provider_round_is_the_only_matchweek_source(
    label: str | None, expected: int | None
) -> None:
    assert matchweek_from_round(label) == expected


def test_local_season_inference_uses_the_premier_league_boundary() -> None:
    assert active_season_start_year(datetime(2026, 6, 30, tzinfo=UTC), None) == 2025
    assert active_season_start_year(datetime(2026, 7, 1, tzinfo=UTC), None) == 2026
    assert active_season_start_year(datetime(2026, 1, 1, tzinfo=UTC), 2024) == 2024
    with pytest.raises(ValueError, match="timezone"):
        active_season_start_year(datetime(2026, 8, 14), None)


def test_fixture_cursor_accepts_both_documented_names() -> None:
    assert next_cursor({"meta": {"nextCursor": "abc"}}) == "abc"
    assert next_cursor({"meta": {"next_cursor": "def"}}) == "def"
    assert next_cursor({"meta": {}}) is None
    assert next_cursor([]) is None


def test_duplicate_fixture_selection_prefers_canonical_utc_record_regardless_of_order() -> None:
    canonical = {
        "id": "fx_utc",
        "date": "2026-08-21T19:00:00Z",
        "time": None,
        "status": {"short": "FT"},
        "round": "Matchday 1",
        "league": {"id": "en.1", "name": "Premier League", "season": 2026},
        "home": {"id": "arsenal-a", "name": "Arsenal FC"},
        "away": {"id": "coventry", "name": "Coventry City FC"},
        "score": {"home": 3, "away": 0},
    }
    local_clock_mirror = {
        "id": "fx_local_clock",
        "date": "2026-08-21T20:00:00Z",
        "time": "20:00",
        "status": {"short": "FT"},
        "round": "Matchday 1",
        "league": {"id": "en.1", "name": "Premier League", "season": 2026},
        "home": {"id": "arsenal-b", "name": "Arsenal"},
        "away": {"id": "coventry", "name": "Coventry City"},
        "score": {"home": 3, "away": 0},
    }

    for rows in (
        [canonical, local_clock_mirror],
        [local_clock_mirror, canonical],
    ):
        fixtures = FixtureEnvelope.model_validate({"data": rows}).data
        selected = select_canonical_provider_fixtures(fixtures)
        assert len(selected) == 1
        assert selected[0].id == "fx_utc"
