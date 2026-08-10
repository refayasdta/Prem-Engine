"""PostgreSQL integration tests for historical identity and provenance rules."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from prem_engine_api.domain.enums import KickoffPrecision
from prem_engine_api.domain.models import (
    ActualResultRevision,
    ClubAlias,
    HistoricalMatchRecord,
    HistoricalSourceFile,
    Match,
    MatchExternalReference,
)
from prem_engine_api.historical.export import (
    build_coverage_report,
    export_benchmark_odds,
    export_training_matches,
    record_is_available,
)
from prem_engine_api.historical.service import import_historical_csv
from prem_engine_api.providers.raw_storage import LocalRawResponseStore
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

SOURCE_URL = "https://www.football-data.co.uk/mmz4281/2021/E0.csv"
CSV_BODY = (
    b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,Referee,"
    b"HS,AS,HST,AST,HC,AC,HF,AF,HY,AY,HR,AR,B365H,B365D,B365A\n"
    b"E0,12/09/2020,12:30,Fulham,Arsenal,0,3,A,0,1,A,C Kavanagh,"
    b"5,13,2,6,2,3,12,12,2,2,0,0,6.00,4.33,1.53\n"
    b"E0,13/09/2020,,West Brom,Leicester,0,3,A,0,0,D,A Taylor,"
    b"7,13,1,7,2,5,12,9,1,1,0,0,3.80,3.60,1.95\n"
)


@pytest.mark.asyncio
async def test_import_is_idempotent_and_preserves_time_precision(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    retrieved_at = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)
    arguments = {
        "body": CSV_BODY,
        "source_url": SOURCE_URL,
        "retrieved_at": retrieved_at,
        "season_start_year": 2020,
        "alias_registry_path": Path("data/mappings/football-data-clubs.csv"),
        "raw_store": LocalRawResponseStore(tmp_path),
    }

    first = await import_historical_csv(db_session, **arguments)
    second = await import_historical_csv(db_session, **arguments)

    assert first.source_rows == 2
    assert first.matches_created == 2
    assert first.results_created == 2
    assert second.reused_existing_source is True
    assert await db_session.scalar(select(func.count()).select_from(HistoricalSourceFile)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Match)) == 2
    assert await db_session.scalar(select(func.count()).select_from(MatchExternalReference)) == 2
    assert await db_session.scalar(select(func.count()).select_from(HistoricalMatchRecord)) == 2
    assert await db_session.scalar(select(func.count()).select_from(ClubAlias)) >= 50
    matches = list(await db_session.scalars(select(Match).order_by(Match.current_kickoff_at)))
    assert {match.kickoff_precision for match in matches} == {
        KickoffPrecision.EXACT,
        KickoffPrecision.DATE_ONLY,
    }
    assert len(list(tmp_path.rglob("*.csv.gz"))) == 1


@pytest.mark.asyncio
async def test_changed_source_creates_result_revision_not_duplicate_match(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    first_retrieval = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)
    common = {
        "source_url": SOURCE_URL,
        "season_start_year": 2020,
        "alias_registry_path": Path("data/mappings/football-data-clubs.csv"),
        "raw_store": LocalRawResponseStore(tmp_path),
    }
    await import_historical_csv(
        db_session,
        body=CSV_BODY,
        retrieved_at=first_retrieval,
        **common,
    )
    corrected = CSV_BODY.replace(b"Fulham,Arsenal,0,3,A", b"Fulham,Arsenal,1,3,A")
    summary = await import_historical_csv(
        db_session,
        body=corrected,
        retrieved_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
        **common,
    )

    assert summary.matches_created == 0
    assert summary.corrections_created == 1
    assert await db_session.scalar(select(func.count()).select_from(Match)) == 2
    assert await db_session.scalar(select(func.count()).select_from(HistoricalSourceFile)) == 2
    fulham_reference = await db_session.scalar(
        select(MatchExternalReference).where(
            MatchExternalReference.external_fixture_id.contains(":fulham:arsenal")
        )
    )
    assert fulham_reference is not None
    revisions = list(
        await db_session.scalars(
            select(ActualResultRevision)
            .where(ActualResultRevision.match_uuid == fulham_reference.match_uuid)
            .order_by(ActualResultRevision.revision_number)
        )
    )
    assert [(revision.home_goals, revision.accepted) for revision in revisions] == [
        (0, False),
        (1, True),
    ]


@pytest.mark.asyncio
async def test_exports_separate_training_data_from_ambiguous_odds(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await import_historical_csv(
        db_session,
        body=CSV_BODY,
        source_url=SOURCE_URL,
        retrieved_at=datetime(2026, 8, 7, 8, 0, tzinfo=UTC),
        season_start_year=2020,
        alias_registry_path=Path("data/mappings/football-data-clubs.csv"),
        raw_store=LocalRawResponseStore(tmp_path / "raw"),
    )
    db_session.add(
        HistoricalSourceFile(
            provider="historical-fpl",
            competition_code="EPL",
            season_label="2020/21",
            source_url="https://example.test/2020-21/players_raw.csv",
            retrieved_at=datetime(2026, 8, 10, tzinfo=UTC),
            response_checksum="f" * 64,
            object_key="historicalfpl/2026/08/10/players.csv.gz",
            schema_fingerprint="e" * 64,
            row_count=700,
        )
    )
    await db_session.flush()

    training = await export_training_matches(db_session, tmp_path / "training.csv")
    odds = await export_benchmark_odds(db_session, tmp_path / "odds.csv")
    report = await build_coverage_report(db_session, generated_at=datetime(2026, 8, 7, tzinfo=UTC))
    training_text = training.path.read_text(encoding="utf-8")
    odds_text = odds.path.read_text(encoding="utf-8")

    assert training.row_count == 2
    assert "B365H" not in training_text
    assert "lagged_history_only" in training_text
    assert odds.row_count == 2
    assert "mixed_or_unknown" in odds_text
    assert report["total_rows"] == 2
    assert report["seasons"][0]["complete_schedule"] is False
    assert report["seasons"][0]["odds_training_eligible_rows"] == 0


def test_availability_rule_excludes_current_and_future_matches() -> None:
    available_after = datetime(2025, 1, 1, 18, 0, tzinfo=UTC)

    assert record_is_available(
        available_after=available_after,
        feature_cutoff_at=datetime(2025, 1, 2, tzinfo=UTC),
    )
    assert not record_is_available(
        available_after=available_after,
        feature_cutoff_at=available_after,
    )
