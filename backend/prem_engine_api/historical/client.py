"""Bounded HTTP client for public Football-Data.co.uk season files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

MAX_SEASON_FILE_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class DownloadedSeason:
    source_url: str
    retrieved_at: datetime
    body: bytes


def season_segment(start_year: int) -> str:
    """Convert 2020 to Football-Data's 2021 path segment."""

    if start_year < 1993 or start_year > 2098:
        raise ValueError("season start year is outside the supported range")
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def source_url(base_url: str, start_year: int) -> str:
    return f"{base_url.rstrip('/')}/{season_segment(start_year)}/E0.csv"


class FootballDataClient:
    """Download one immutable public CSV at a time without redirects to other hosts."""

    def __init__(self, *, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def download_season(self, start_year: int) -> DownloadedSeason:
        url = source_url(self._base_url, start_year)
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(30.0),
            follow_redirects=False,
            headers={"User-Agent": "Prem-Engine historical importer/0.1"},
        ) as client:
            response = await client.get(url)
        response.raise_for_status()
        if len(response.content) > MAX_SEASON_FILE_BYTES:
            raise ValueError("historical season file exceeds the 5 MiB safety limit")
        return DownloadedSeason(
            source_url=url,
            retrieved_at=datetime.now(UTC),
            body=response.content,
        )
