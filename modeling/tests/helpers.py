"""Small deterministic modeling datasets used across Phase 6 tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_DNS, uuid5

from prem_engine_modeling.data import HistoricalDataset, MatchRecord, MatchResult


def club_uuid(name: str) -> str:
    return str(uuid5(NAMESPACE_DNS, f"prem-engine-test-club:{name}"))


def match_record(
    *,
    identifier: str,
    season: str,
    kickoff_at: datetime,
    home: str = "Alpha",
    away: str = "Beta",
    home_goals: int = 1,
    away_goals: int = 0,
    available_delay: timedelta = timedelta(hours=3),
) -> MatchRecord:
    result: MatchResult = (
        "H" if home_goals > away_goals else "A" if home_goals < away_goals else "D"
    )
    return MatchRecord(
        match_uuid=str(uuid5(NAMESPACE_DNS, f"prem-engine-test-match:{identifier}")),
        season=season,
        kickoff_at=kickoff_at,
        available_after=kickoff_at + available_delay,
        home_club_uuid=club_uuid(home),
        home_club=home,
        away_club_uuid=club_uuid(away),
        away_club=away,
        home_goals=home_goals,
        away_goals=away_goals,
        result=result,
    )


def six_season_dataset() -> HistoricalDataset:
    seasons = ("2020/21", "2021/22", "2022/23", "2023/24", "2024/25", "2025/26")
    records: list[MatchRecord] = []
    fixtures = (
        ("Alpha", "Beta", 2, 0),
        ("Gamma", "Delta", 1, 1),
        ("Beta", "Gamma", 0, 1),
        ("Delta", "Alpha", 0, 2),
    )
    for season_index, season in enumerate(seasons):
        for fixture_index, (home, away, home_goals, away_goals) in enumerate(fixtures):
            kickoff = datetime(2020 + season_index, 8, 1, 12, 0, tzinfo=UTC) + timedelta(
                days=fixture_index * 7
            )
            records.append(
                match_record(
                    identifier=f"{season}-{fixture_index}",
                    season=season,
                    kickoff_at=kickoff,
                    home=home,
                    away=away,
                    home_goals=home_goals,
                    away_goals=away_goals,
                )
            )
    return HistoricalDataset(records=tuple(records), checksum="d" * 64, seasons=seasons)
