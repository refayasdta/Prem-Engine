"""Pure scheduling and provider-pagination contracts for local synchronization."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from prem_engine_api.ingestion.fixtures import matchweek_from_round
from prem_engine_api.local_sync import active_season_start_year, next_cursor


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
