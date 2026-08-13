"""Historical FPL archive and canonical import invariants."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from prem_engine_api.domain.enums import FixtureStatus
from prem_engine_api.domain.models import (
    Club,
    Competition,
    Match,
    PlayerMatchPerformance,
    Season,
)
from prem_engine_api.providers.historical_fpl.archive import (
    ArchivedCsv,
    ArchivedSeason,
    HistoricalFplArchive,
    HistoricalFplArchiveError,
)
from prem_engine_api.providers.historical_fpl.audit import parse_csv
from prem_engine_api.providers.historical_fpl.importer import import_historical_fpl_seasons
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _csv(rows: list[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=tuple(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def _source(kind: str, body: bytes) -> ArchivedCsv:
    return ArchivedCsv(
        kind=kind,
        season="2020-21",
        checksum=hashlib.sha256(body).hexdigest(),
        object_key=f"historicalfpl/2026/08/10/{kind}.csv.gz",
        retrieved_at=datetime(2026, 8, 10, tzinfo=UTC),
        source_url=f"https://example.test/2020-21/{kind}.csv",
        parsed=parse_csv(body),
    )


def _season(start_indicator_available: bool = False) -> ArchivedSeason:
    merged_rows = [
        {
            "element": 1,
            "fixture": 10,
            "kickoff_time": "2020-09-12T12:30:00Z",
            "minutes": 90,
            "team": "Alpha",
            "position": "GK",
            "goals_scored": 0,
            "assists": 0,
            "was_home": "True",
            "starts": "" if not start_indicator_available else "1",
            "total_points": 6,
        },
        {
            "element": 2,
            "fixture": 10,
            "kickoff_time": "2020-09-12T12:30:00Z",
            "minutes": 90,
            "team": "Beta",
            "position": "FWD",
            "goals_scored": 1,
            "assists": 0,
            "was_home": "False",
            "starts": "" if not start_indicator_available else "1",
            "total_points": 8,
        },
    ]
    merged_rows.append(dict(merged_rows[0]))
    merged = _csv(merged_rows)
    players = _csv(
        [
            {"id": 1, "code": 101, "first_name": "Ada", "second_name": "Keeper"},
            {"id": 2, "code": 102, "first_name": "Bea", "second_name": "Forward"},
        ]
    )
    fixtures = _csv(
        [
            {
                "id": 10,
                "kickoff_time": "2020-09-12T12:30:00Z",
                "team_h": 1,
                "team_a": 2,
            }
        ]
    )
    return ArchivedSeason(
        season="2020-21",
        merged=_source("merged", merged),
        players=_source("players", players),
        fixtures=_source("fixtures", fixtures),
        stable_player_code_column="code",
        start_indicator_available=start_indicator_available,
    )


@pytest.mark.asyncio
async def test_import_is_idempotent_and_preserves_unknown_starts(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    competition = Competition(slug="premier-league", name="Premier League", country_code="GB")
    home = Club(canonical_name="Alpha FC", short_name="Alpha")
    away = Club(canonical_name="Beta FC", short_name="Beta")
    db_session.add_all((competition, home, away))
    await db_session.flush()
    season = Season(
        competition_uuid=competition.competition_uuid,
        label="2020/21",
        start_date=date(2020, 7, 1),
        end_date=date(2021, 6, 30),
    )
    db_session.add(season)
    await db_session.flush()
    kickoff = datetime(2020, 9, 12, 12, 30, tzinfo=UTC)
    db_session.add(
        Match(
            season_uuid=season.season_uuid,
            home_club_uuid=home.club_uuid,
            away_club_uuid=away.club_uuid,
            status=FixtureStatus.FINISHED,
            current_kickoff_at=kickoff,
            prediction_due_at=kickoff - timedelta(hours=24),
        )
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text(
        "source_alias,canonical_name,short_name,active\n"
        "Alpha,Alpha FC,Alpha,true\n"
        "Beta,Beta FC,Beta,true\n",
        encoding="utf-8",
    )

    first = await import_historical_fpl_seasons(
        db_session, seasons=(_season(),), alias_registry_path=aliases
    )
    second = await import_historical_fpl_seasons(
        db_session, seasons=(_season(),), alias_registry_path=aliases
    )

    assert first.performances_created == 2
    assert first.performances_reused == 1
    assert first.unknown_start_records == 2
    assert second.performances_created == 0
    assert second.performances_reused == 3
    assert await db_session.scalar(select(func.count()).select_from(PlayerMatchPerformance)) == 2
    observations = list(await db_session.scalars(select(PlayerMatchPerformance)))
    assert all(item.started is None for item in observations)
    assert all(item.starting_status_source == "unknown" for item in observations)
    assert all(item.available_after == kickoff + timedelta(hours=4) for item in observations)


def test_archive_rejects_capture_checksum_mismatch(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "historicalfpl" / "2026" / "08" / "10"
    raw.mkdir(parents=True)
    checksum = "a" * 64
    capture = raw / f"010203000000_capture_{checksum[:12]}.csv.gz"
    capture.write_bytes(gzip.compress(b"id\n1\n"))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "contract_version": "historical-fpl-coverage-audit-v1",
                "sanitized": True,
                "raw_responses_stored_locally": True,
                "seasons": [
                    {
                        "season": "2020-21",
                        "available": True,
                        "source_checksums": {
                            "merged": checksum,
                            "players": checksum,
                            "fixtures": checksum,
                        },
                        "stable_player_code_column": "code",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    archive = HistoricalFplArchive(
        manifest_path=manifest,
        raw_root=tmp_path / "raw" / "historicalfpl",
        base_url="https://example.test",
    )
    with pytest.raises(HistoricalFplArchiveError, match="checksum mismatch"):
        archive.seasons()
