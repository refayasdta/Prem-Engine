"""Run a bounded, sanitized API-Football Premier League coverage audit."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from prem_engine_api.config import get_settings
from prem_engine_api.providers.api_football.client import (
    ApiFootballAuditClient,
    ApiFootballAuditResponse,
)
from prem_engine_api.providers.api_football.contracts import (
    first_fixture_id,
    league_coverage,
    provider_error_keys,
)
from prem_engine_api.providers.raw_storage import LocalRawResponseStore

DEFAULT_OUTPUT = Path("data/contracts/api-football/coverage-summary.json")
DEFAULT_SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", type=int, default=39)
    parser.add_argument("--seasons", nargs="+", type=int, default=DEFAULT_SEASONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--confirm-live-audit",
        action="store_true",
        help="Required acknowledgement that this command consumes provider requests.",
    )
    return parser.parse_args()


def describe_shape(value: Any, depth: int = 0) -> Any:
    """Retain field names and structural types without retaining provider values."""

    if depth >= 6:
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


def summarize_response(response: ApiFootballAuditResponse) -> dict[str, Any]:
    """Create evidence suitable for review and possible source control."""

    envelope = response.envelope
    sample = envelope.response[0] if envelope.response else None
    return {
        "status_code": response.status_code,
        "provider_errors_present": envelope.has_errors,
        "provider_error_keys": provider_error_keys(envelope),
        "result_count": envelope.results,
        "response_item_count": len(envelope.response),
        "sample_item_shape": describe_shape(sample),
        "rate_window": {
            "daily_limit": response.rate_window.daily_limit,
            "daily_remaining": response.rate_window.daily_remaining,
            "minute_limit": response.rate_window.minute_limit,
            "minute_remaining": response.rate_window.minute_remaining,
        },
        "raw_response_captured": True,
        "raw_response_checksum": response.raw_checksum,
    }


async def run_probe(args: argparse.Namespace) -> None:
    if not args.confirm_live_audit:
        raise SystemExit(
            "Live audit not confirmed; no requests were made. "
            "Re-run with --confirm-live-audit after approval."
        )
    settings = get_settings()
    if settings.api_football_key is None:
        raise SystemExit("API_FOOTBALL_KEY is not configured; no requests were made")
    required_requests = len(args.seasons) * 4
    if required_requests > settings.api_football_audit_request_limit:
        raise SystemExit(
            f"Audit needs {required_requests} requests but the configured audit limit is "
            f"{settings.api_football_audit_request_limit}; no requests were made"
        )

    seasons: list[dict[str, Any]] = []
    async with ApiFootballAuditClient(
        settings=settings,
        raw_store=LocalRawResponseStore(settings.raw_data_root),
        max_requests=required_requests,
    ) as client:
        for season in args.seasons:
            coverage_response = await client.get(
                "/leagues", params={"id": args.league, "season": season}
            )
            fixture_response = await client.get(
                "/fixtures",
                params={"league": args.league, "season": season, "status": "FT"},
            )
            fixture_id = first_fixture_id(fixture_response.envelope)
            if fixture_id is None:
                lineups: dict[str, Any] = {"not_requested": "no_sample_fixture"}
                player_statistics: dict[str, Any] = {"not_requested": "no_sample_fixture"}
            else:
                lineups = summarize_response(
                    await client.get("/fixtures/lineups", params={"fixture": fixture_id})
                )
                player_statistics = summarize_response(
                    await client.get("/fixtures/players", params={"fixture": fixture_id})
                )
            seasons.append(
                {
                    "season": season,
                    "declared_coverage": league_coverage(coverage_response.envelope, season),
                    "coverage_response": summarize_response(coverage_response),
                    "fixture_discovery": summarize_response(fixture_response),
                    "sample_lineups": lineups,
                    "sample_player_statistics": player_statistics,
                }
            )

        summary = {
            "contract_version": "api-football-coverage-audit-v1",
            "sanitized": True,
            "league_id": args.league,
            "seasons": seasons,
            "request_count": client.request_count,
            "maximum_request_count": required_requests,
            "raw_responses_stored_locally": True,
            "training_started": False,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote sanitized API-Football coverage evidence to {args.output}")
    print(f"Requests consumed: {summary['request_count']} of {required_requests} allowed")
    print("Training was not started.")


def main() -> None:
    asyncio.run(run_probe(parse_args()))


if __name__ == "__main__":
    main()
