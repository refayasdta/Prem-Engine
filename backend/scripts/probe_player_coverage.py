"""Run a bounded, sanitized Phase 10 player-data coverage probe."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.domain.models import ProviderRequest
from prem_engine_api.providers.kickoffapi.client import KickoffApiClient
from prem_engine_api.providers.kickoffapi.contracts import (
    FixtureEnvelope,
    validate_endpoint_payload,
)
from prem_engine_api.providers.raw_storage import LocalRawResponseStore
from pydantic import ValidationError
from sqlalchemy import select

DEFAULT_OUTPUT = Path("data/contracts/kickoffapi/player-coverage-summary.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default="en.1")
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def describe_shape(value: Any, depth: int = 0) -> Any:
    """Retain structural evidence without committing provider values."""

    if depth >= 5:
        return type(value).__name__
    if isinstance(value, dict):
        return {str(key): describe_shape(child, depth + 1) for key, child in value.items()}
    if isinstance(value, list):
        return {
            "type": "list",
            "length": len(value),
            "item": describe_shape(value[0], depth + 1) if value else None,
        }
    if value is None:
        return "null"
    return type(value).__name__


def coverage_state(payload: Any) -> str:
    if not isinstance(payload, dict) or "data" not in payload:
        return "unknown_shape"
    data = payload["data"]
    if isinstance(data, list):
        return "available" if data else "empty"
    return "available" if data is not None else "empty"


async def run_probe(args: argparse.Namespace) -> None:
    settings = get_settings()
    if settings.kickoff_api_key is None:
        raise SystemExit("KICKOFF_API_KEY is not configured; no requests were made")

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    results: list[dict[str, Any]] = []

    async def request(
        client: KickoffApiClient,
        *,
        name: str,
        endpoint: str,
        endpoint_template: str,
        params: dict[str, str | int | float | bool] | None = None,
    ) -> Any | None:
        try:
            captured = await client.get(endpoint, params=params)
        except httpx.HTTPStatusError as error:
            async with session_factory() as session:
                ledger = await session.scalar(
                    select(ProviderRequest)
                    .where(ProviderRequest.endpoint == endpoint)
                    .order_by(ProviderRequest.requested_at.desc())
                    .limit(1)
                )
            results.append(
                {
                    "name": name,
                    "endpoint": endpoint_template,
                    "status_code": error.response.status_code,
                    "rate_limit": ledger.rate_limit if ledger else None,
                    "rate_remaining": ledger.rate_remaining if ledger else None,
                    "provider_request_id_present": bool(
                        ledger and ledger.provider_request_id is not None
                    ),
                    "coverage": "unavailable",
                    "contract_valid": False,
                    "response_shape": None,
                }
            )
            return None
        contract_valid = True
        contract_error: str | None = None
        try:
            validate_endpoint_payload(endpoint, captured.payload)
        except (ValidationError, ValueError) as error:
            contract_valid = False
            contract_error = type(error).__name__
        async with session_factory() as session:
            ledger = await session.get(ProviderRequest, captured.provider_request_uuid)
        if ledger is None:
            raise RuntimeError("probe request ledger row disappeared")
        result: dict[str, Any] = {
            "name": name,
            "endpoint": endpoint_template,
            "status_code": ledger.response_status,
            "rate_limit": ledger.rate_limit,
            "rate_remaining": ledger.rate_remaining,
            "provider_request_id_present": ledger.provider_request_id is not None,
            "coverage": coverage_state(captured.payload),
            "contract_valid": contract_valid,
            "response_shape": describe_shape(captured.payload),
        }
        if contract_error is not None:
            result["contract_error"] = contract_error
        results.append(result)
        return captured.payload

    try:
        async with KickoffApiClient(
            settings=settings,
            session_factory=session_factory,
            raw_store=LocalRawResponseStore(settings.raw_data_root),
        ) as client:
            await request(
                client,
                name="players",
                endpoint="/api/v2/players",
                endpoint_template="/api/v2/players",
                params={"limit": 5},
            )
            fixtures_payload = await request(
                client,
                name="historical_fixtures",
                endpoint="/api/v2/fixtures",
                endpoint_template="/api/v2/fixtures",
                params={"league": args.league, "season": args.season, "limit": 5},
            )
            if fixtures_payload is None:
                raise RuntimeError("fixture discovery failed; dependent probes were not attempted")
            fixtures = FixtureEnvelope.model_validate(fixtures_payload)
            if not fixtures.data:
                raise RuntimeError("fixture discovery returned no historical fixture")
            fixture = fixtures.data[0]
            team_id = fixture.normalized_home.id
            fixture_id = fixture.id
            await request(
                client,
                name="team_squad",
                endpoint=f"/api/v2/teams/{team_id}/squad",
                endpoint_template="/api/v2/teams/:id/squad",
            )
            await request(
                client,
                name="fixture_lineups",
                endpoint=f"/api/v2/fixtures/{fixture_id}/lineups",
                endpoint_template="/api/v2/fixtures/:id/lineups",
            )
            await request(
                client,
                name="fixture_players",
                endpoint=f"/api/v2/fixtures/{fixture_id}/players",
                endpoint_template="/api/v2/fixtures/:id/players",
            )
            await request(
                client,
                name="injuries",
                endpoint="/api/v2/injuries",
                endpoint_template="/api/v2/injuries",
                params={"team": team_id, "limit": 5},
            )
            await request(
                client,
                name="transfers",
                endpoint="/api/v2/transfers",
                endpoint_template="/api/v2/transfers",
                params={"team": team_id, "limit": 5},
            )
    finally:
        await engine.dispose()

    summary = {
        "contract_version": "kickoffapi-player-coverage-v1",
        "sanitized": True,
        "requested_season": args.season,
        "request_count": len(results),
        "probes": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote sanitized player coverage evidence to {args.output}")


def main() -> None:
    asyncio.run(run_probe(parse_args()))


if __name__ == "__main__":
    main()
