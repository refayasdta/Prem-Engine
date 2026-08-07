"""Quota, ledger, and raw-capture integration for the provider client."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import ProviderRequestStatus
from prem_engine_api.domain.models import ProviderRequest, RawFetch
from prem_engine_api.ingestion.sync import sync_fixtures
from prem_engine_api.providers.kickoffapi.client import KickoffApiClient
from prem_engine_api.providers.raw_storage import LocalRawResponseStore
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_client_accounts_for_and_captures_each_response(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    connection = await db_session.connection()
    session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "test-secret"
        return httpx.Response(
            200,
            json={"data": [], "meta": {"count": 0}},
            headers={
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "84",
                "X-RateLimit-Reset": "1786147200",
                "X-Request-Id": "request-test",
            },
            request=request,
        )

    settings = Settings(
        kickoff_api_key=SecretStr("test-secret"),
        kickoff_daily_request_limit=100,
        kickoff_operational_request_limit=85,
        raw_data_root=tmp_path,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.kickoffapi.com"
    ) as http_client:
        client = KickoffApiClient(
            settings=settings,
            session_factory=session_factory,
            raw_store=LocalRawResponseStore(tmp_path),
            http_client=http_client,
        )
        first = await client.get("/api/v2/fixtures", params={"league": "en.1", "limit": 1})
        second = await client.get("/api/v2/fixtures", params={"league": "en.1", "limit": 1})
        sync_outcome = await sync_fixtures(
            client=client,
            session_factory=session_factory,
            league="en.1",
            season=2026,
            limit=1,
        )

    assert first.raw_fetch_uuid != second.raw_fetch_uuid
    assert sync_outcome.ingestion.received == 0
    request_uuids = {
        first.provider_request_uuid,
        second.provider_request_uuid,
        sync_outcome.provider_request_uuid,
    }
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ProviderRequest)
            .where(
                ProviderRequest.provider_request_uuid.in_(request_uuids),
                ProviderRequest.status == ProviderRequestStatus.SUCCEEDED,
            )
        )
        == 3
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(RawFetch)
            .where(RawFetch.provider_request_uuid.in_(request_uuids))
        )
        == 3
    )
    request_row = await db_session.get(ProviderRequest, first.provider_request_uuid)
    assert request_row is not None
    assert request_row.rate_limit == 100
    assert request_row.rate_remaining == 84
    assert request_row.provider_request_id == "request-test"
