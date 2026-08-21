"""Official current-FPL fallback contract, capture, and canonical ingestion tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import ProviderRequestStatus
from prem_engine_api.domain.models import (
    Club,
    Player,
    ProviderRequest,
    RawFetch,
    Season,
    SquadMembership,
)
from prem_engine_api.ingestion.current_fpl import ingest_current_fpl_squads
from prem_engine_api.providers.current_fpl.client import CurrentFplClient
from prem_engine_api.providers.current_fpl.contracts import CurrentFplBootstrap
from prem_engine_api.providers.raw_storage import LocalRawResponseStore
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _payload() -> dict[str, object]:
    return {
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}],
        "elements": [
            {
                "id": 10,
                "first_name": "David",
                "second_name": "Raya",
                "web_name": "Raya",
                "team": 1,
                "element_type": 1,
                "squad_number": 1,
            },
            {
                "id": 11,
                "first_name": "Test",
                "second_name": "Defender",
                "web_name": "Defender",
                "team": 1,
                "element_type": 2,
                "squad_number": 2,
            },
        ],
    }


def test_bootstrap_contract_rejects_unknown_position() -> None:
    payload = _payload()
    payload["elements"][0]["element_type"] = 5  # type: ignore[index]
    with pytest.raises(ValueError):
        CurrentFplBootstrap.model_validate(payload)


@pytest.mark.asyncio
async def test_client_captures_and_accounts_for_bootstrap(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    connection = await db_session.connection()
    sessions = async_sessionmaker(bind=connection, expire_on_commit=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/bootstrap-static/"
        assert request.headers["user-agent"].startswith("Prem-Engine/")
        return httpx.Response(200, json=_payload(), request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://fantasy.premierleague.com"
    ) as http_client:
        client = CurrentFplClient(
            settings=Settings(raw_data_root=tmp_path),
            session_factory=sessions,
            raw_store=LocalRawResponseStore(tmp_path),
            http_client=http_client,
        )
        captured = await client.get_bootstrap()

    request = await db_session.get(ProviderRequest, captured.provider_request_uuid)
    assert request is not None and request.status == ProviderRequestStatus.SUCCEEDED
    assert await db_session.get(RawFetch, captured.raw_fetch_uuid) is not None


@pytest.mark.asyncio
async def test_ingestion_maps_only_target_club_and_is_idempotent(db_session: AsyncSession) -> None:
    from prem_engine_api.domain.models import Competition

    competition = Competition(slug="fpl-test", name="Premier League", country_code="GB")
    arsenal = Club(canonical_name="Arsenal FC", short_name="Arsenal")
    ignored = Club(canonical_name="Chelsea FC", short_name="Chelsea")
    db_session.add_all((competition, arsenal, ignored))
    await db_session.flush()
    season = Season(
        competition_uuid=competition.competition_uuid,
        label="2026/27",
        start_date=date(2026, 8, 1),
        end_date=date(2027, 5, 31),
    )
    db_session.add(season)
    await db_session.flush()
    now = datetime(2026, 8, 21, tzinfo=UTC)
    first = await ingest_current_fpl_squads(
        db_session,
        _payload(),
        season_uuid=season.season_uuid,
        target_club_uuids={arsenal.club_uuid},
        observed_at=now,
    )
    second = await ingest_current_fpl_squads(
        db_session,
        _payload(),
        season_uuid=season.season_uuid,
        target_club_uuids={arsenal.club_uuid},
        observed_at=now,
    )

    assert first.created == 2
    assert second.unchanged == 2
    assert await db_session.scalar(select(func.count()).select_from(Player)) == 2
    positions = set(await db_session.scalars(select(SquadMembership.primary_position)))
    assert positions == {"Goalkeeper", "Defender"}
