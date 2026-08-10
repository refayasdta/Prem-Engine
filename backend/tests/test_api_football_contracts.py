from __future__ import annotations

import json

import httpx
import pytest
from prem_engine_api.config import Settings
from prem_engine_api.providers.api_football.client import (
    ApiFootballAuditBudgetError,
    ApiFootballAuditClient,
    MissingApiFootballCredentialError,
)
from prem_engine_api.providers.api_football.contracts import (
    ApiFootballEnvelope,
    first_fixture_id,
    league_coverage,
    provider_error_keys,
)
from prem_engine_api.providers.raw_storage import LocalRawResponseStore


def envelope_payload() -> dict[str, object]:
    return {
        "get": "fixtures",
        "parameters": {"league": "39", "season": "2025"},
        "errors": [],
        "results": 1,
        "paging": {"current": 1, "total": 1},
        "response": [{"fixture": {"id": 12345}}],
    }


def test_contract_extracts_fixture_and_public_coverage_flags() -> None:
    fixture = ApiFootballEnvelope.model_validate(envelope_payload())
    coverage = ApiFootballEnvelope.model_validate(
        {
            "get": "leagues",
            "parameters": {},
            "errors": {},
            "results": 1,
            "paging": {"current": 1, "total": 1},
            "response": [
                {
                    "seasons": [
                        {
                            "year": 2025,
                            "coverage": {
                                "fixtures": {
                                    "lineups": True,
                                    "statistics_fixtures": True,
                                    "statistics_players": True,
                                },
                                "players": True,
                                "injuries": True,
                            },
                        }
                    ]
                }
            ],
        }
    )

    assert first_fixture_id(fixture) == 12345
    assert league_coverage(coverage, 2025) == {
        "lineups": True,
        "fixture_statistics": True,
        "player_statistics": True,
        "players": True,
        "injuries": True,
    }


def test_contract_sanitizes_provider_error_messages() -> None:
    payload = envelope_payload()
    payload["parameters"] = []
    payload["errors"] = {"token": "secret provider message"}
    envelope = ApiFootballEnvelope.model_validate(payload)

    assert envelope.has_errors is True
    assert envelope.parameters == []
    assert provider_error_keys(envelope) == ["token"]
    assert "secret provider message" not in str(provider_error_keys(envelope))


@pytest.mark.asyncio
async def test_audit_client_captures_raw_response_and_enforces_ceiling(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-apisports-key"] == "configured-test-key"
        return httpx.Response(
            200,
            content=json.dumps(envelope_payload()).encode(),
            headers={
                "x-ratelimit-requests-limit": "100",
                "x-ratelimit-requests-remaining": "99",
                "x-ratelimit-limit": "30",
                "x-ratelimit-remaining": "29",
            },
        )

    settings = Settings(
        api_football_key="configured-test-key",
        api_football_audit_request_limit=1,
    )
    async with ApiFootballAuditClient(
        settings=settings,
        raw_store=LocalRawResponseStore(tmp_path),
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.get("/fixtures", params={"league": 39})
        assert response.rate_window.daily_limit == 100
        assert response.rate_window.minute_limit == 30
        assert (tmp_path / response.raw_object_key).is_file()
        with pytest.raises(ApiFootballAuditBudgetError):
            await client.get("/fixtures")


@pytest.mark.asyncio
async def test_audit_client_refuses_request_without_key(tmp_path) -> None:
    settings = Settings(api_football_key=None)
    async with ApiFootballAuditClient(
        settings=settings,
        raw_store=LocalRawResponseStore(tmp_path),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    ) as client:
        with pytest.raises(MissingApiFootballCredentialError):
            await client.get("/fixtures")
