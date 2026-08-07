"""Run a small, read-only KickoffAPI contract probe.

The script records shapes and rate-limit metadata, never response values or the
API key. It performs at most four requests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

BASE_URL = os.getenv("KICKOFF_API_BASE_URL", "https://api.kickoffapi.com").rstrip("/")
OUTPUT = Path("data/contracts/kickoffapi/probe-summary.json")
PROBES = (
    ("v2_account_status", "/api/v2/account/status", {}),
    ("v1_account_status_fallback", "/api/v1/account/status", {}),
    ("resolve_premier_league", "/api/v2/resolve", {"entity": "league", "legacyId": 39}),
    ("season_fixture_shape", "/api/v2/fixtures", {"season": 2026, "limit": 1}),
)
RATE_HEADERS = (
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "x-request-id",
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


def main() -> None:
    key = os.getenv("KICKOFF_API_KEY")
    if not key:
        raise SystemExit("KICKOFF_API_KEY is not configured; no requests were made")

    results: list[dict[str, Any]] = []
    with httpx.Client(
        base_url=BASE_URL,
        headers={"x-api-key": key, "accept": "application/json"},
        timeout=20,
        follow_redirects=False,
    ) as client:
        for name, path, params in PROBES:
            response = client.get(path, params=params)
            try:
                payload: Any = response.json()
            except json.JSONDecodeError:
                payload = None
            results.append(
                {
                    "name": name,
                    "path": path,
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "rate_limit_headers": {
                        header: response.headers.get(header) for header in RATE_HEADERS
                    },
                    "response_shape": describe_shape(payload),
                }
            )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"request_count": len(results), "probes": results}, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote sanitized contract shapes to {OUTPUT}")


if __name__ == "__main__":
    main()
