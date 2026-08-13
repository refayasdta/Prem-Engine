"""Bounded client for public historical Fantasy Premier League CSV files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from prem_engine_api.config import Settings
from prem_engine_api.providers.raw_storage import RawResponseStore


class HistoricalFplDownloadBudgetError(RuntimeError):
    """Raised before a download would exceed the explicit audit ceiling."""


@dataclass(frozen=True)
class HistoricalFplDownload:
    """One public response and its immutable local capture metadata."""

    path: str
    status_code: int
    body: bytes
    raw_object_key: str
    raw_checksum: str


class HistoricalFplClient:
    """Download a fixed number of public CSV files without hidden retries."""

    def __init__(
        self,
        *,
        settings: Settings,
        raw_store: RawResponseStore,
        max_downloads: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if max_downloads < 1:
            raise ValueError("historical FPL download limit must be positive")
        self._raw_store = raw_store
        self._max_downloads = max_downloads
        self._download_count = 0
        self._client = httpx.AsyncClient(
            base_url=settings.fpl_historical_base_url,
            headers={"User-Agent": "Prem-Engine-Historical-FPL-Audit/1.0"},
            timeout=60.0,
            follow_redirects=True,
            transport=transport,
        )

    @property
    def download_count(self) -> int:
        return self._download_count

    async def __aenter__(self) -> HistoricalFplClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_csv(self, path: str) -> HistoricalFplDownload:
        """Download and append-only capture one expected CSV response."""

        if self._download_count >= self._max_downloads:
            raise HistoricalFplDownloadBudgetError(
                f"historical FPL download limit of {self._max_downloads} reached"
            )
        self._download_count += 1
        fetched_at = datetime.now(UTC)
        response = await self._client.get(path)
        stored = self._raw_store.store(
            provider="historicalfpl",
            body=response.content,
            fetched_at=fetched_at,
            extension="csv",
        )
        return HistoricalFplDownload(
            path=path,
            status_code=response.status_code,
            body=response.content,
            raw_object_key=stored.object_key,
            raw_checksum=stored.checksum,
        )
