"""Idempotent fixture normalization against PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from prem_engine_api.domain.models import (
    ActualResultRevision,
    Club,
    Match,
    MatchExternalReference,
)
from prem_engine_api.ingestion.fixtures import FixtureIngestor
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def fixture_payload(*, status: str = "NS", home_score: int | None = None) -> dict[str, object]:
    return {
        "data": [
            {
                "id": "fx_phase4",
                "date": "2026-08-15T14:00:00Z",
                "status": status,
                "league": {
                    "id": "en.1",
                    "name": "Premier League",
                    "season": 2026,
                    "country": "England",
                },
                "homeTeam": {"id": "t_phase4_home", "name": "Phase Four Home"},
                "awayTeam": {"id": "t_phase4_away", "name": "Phase Four Away"},
                "homeScore": home_score,
                "awayScore": 1 if home_score is not None else None,
            }
        ],
        "count": 1,
    }


@pytest.mark.asyncio
async def test_fixture_ingestion_is_idempotent_and_versions_corrections(
    db_session: AsyncSession,
) -> None:
    ingestor = FixtureIngestor(db_session)
    observed = datetime(2026, 8, 7, tzinfo=UTC)

    first = await ingestor.ingest(fixture_payload(), observed_at=observed)
    second = await ingestor.ingest(fixture_payload(), observed_at=observed)
    assert first.created == 1
    assert second.unchanged == 1
    assert await db_session.scalar(select(func.count()).select_from(Match)) == 1
    assert await db_session.scalar(select(func.count()).select_from(MatchExternalReference)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Club)) == 2

    completed = await ingestor.ingest(
        fixture_payload(status="finished", home_score=2), observed_at=observed
    )
    corrected = await ingestor.ingest(
        fixture_payload(status="finished", home_score=3), observed_at=observed
    )
    assert completed.updated == 1
    assert corrected.updated == 1
    revisions = list(await db_session.scalars(select(ActualResultRevision)))
    assert len(revisions) == 2
    assert sum(revision.accepted for revision in revisions) == 1
    assert next(revision for revision in revisions if revision.accepted).home_goals == 3
