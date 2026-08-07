"""Run a three-request KickoffAPI v2 contract probe through the audited client."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.domain.models import ProviderRequest
from prem_engine_api.providers.kickoffapi.client import KickoffApiClient
from prem_engine_api.providers.kickoffapi.contracts import validate_endpoint_payload
from prem_engine_api.providers.raw_storage import LocalRawResponseStore

OUTPUT = Path("data/contracts/kickoffapi/probe-summary.json")
PROBES = (
    ("v2_leagues", "/api/v2/leagues", {"country": "England", "limit": 1}),
    ("v2_teams", "/api/v2/teams", {"league": "en.1", "limit": 1}),
    ("v2_fixtures", "/api/v2/fixtures", {"league": "en.1", "season": 2026, "limit": 1}),
)


def describe_shape(value: Any, depth: int = 0) -> Any:
    """Return structural type information without preserving provider values."""

    if depth >= 4:
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


async def run_probe() -> None:
    settings = get_settings()
    if settings.kickoff_api_key is None:
        raise SystemExit("KICKOFF_API_KEY is not configured; no requests were made")

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    results: list[dict[str, Any]] = []
    try:
        async with KickoffApiClient(
            settings=settings,
            session_factory=session_factory,
            raw_store=LocalRawResponseStore(settings.raw_data_root),
        ) as client:
            for name, endpoint, params in PROBES:
                captured = await client.get(endpoint, params=params)
                validate_endpoint_payload(endpoint, captured.payload)
                async with session_factory() as session:
                    request = await session.get(ProviderRequest, captured.provider_request_uuid)
                    if request is None:
                        raise RuntimeError("probe request ledger row disappeared")
                    results.append(
                        {
                            "name": name,
                            "endpoint": endpoint,
                            "status_code": request.response_status,
                            "rate_limit": request.rate_limit,
                            "rate_remaining": request.rate_remaining,
                            "provider_request_id_present": request.provider_request_id is not None,
                            "contract_valid": True,
                            "response_shape": describe_shape(captured.payload),
                        }
                    )
    finally:
        await engine.dispose()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"request_count": len(results), "probes": results}, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote sanitized contract shapes to {OUTPUT}")


def main() -> None:
    asyncio.run(run_probe())


if __name__ == "__main__":
    main()
