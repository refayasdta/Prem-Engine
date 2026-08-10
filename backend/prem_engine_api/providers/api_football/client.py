"""Strictly bounded API-Football client used only for the coverage audit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from pydantic import ValidationError

from prem_engine_api.config import Settings
from prem_engine_api.providers.api_football.contracts import ApiFootballEnvelope
from prem_engine_api.providers.raw_storage import LocalRawResponseStore


class MissingApiFootballCredentialError(RuntimeError):
    """Raised before any request when no API-Football key is configured."""


class ApiFootballAuditBudgetError(RuntimeError):
    """Raised before a request would exceed the explicit audit ceiling."""


class ApiFootballContractError(RuntimeError):
    """Raised when a response is not a valid API-Football envelope."""


@dataclass(frozen=True)
class ApiFootballRateWindow:
    """Daily and minute quota values reported by API-Sports."""

    daily_limit: int | None
    daily_remaining: int | None
    minute_limit: int | None
    minute_remaining: int | None


@dataclass(frozen=True)
class ApiFootballAuditResponse:
    """Validated response plus non-secret audit metadata."""

    status_code: int
    envelope: ApiFootballEnvelope
    rate_window: ApiFootballRateWindow
    raw_object_key: str
    raw_checksum: str


def _integer_header(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


class ApiFootballAuditClient:
    """Make a small, append-only audit without becoming a production sync client."""

    def __init__(
        self,
        *,
        settings: Settings,
        raw_store: LocalRawResponseStore,
        max_requests: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._raw_store = raw_store
        configured_limit = settings.api_football_audit_request_limit
        self._max_requests = max_requests if max_requests is not None else configured_limit
        if self._max_requests < 1:
            raise ValueError("API-Football audit request limit must be positive")
        if self._max_requests > settings.api_football_daily_request_limit:
            raise ValueError("API-Football audit limit cannot exceed the daily limit")
        self._request_count = 0
        key = settings.api_football_key
        headers = {"x-apisports-key": key.get_secret_value()} if key is not None else {}
        self._client = httpx.AsyncClient(
            base_url=settings.api_football_base_url,
            headers=headers,
            timeout=30.0,
            transport=transport,
        )

    @property
    def request_count(self) -> int:
        return self._request_count

    async def __aenter__(self) -> ApiFootballAuditClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self, endpoint: str, *, params: dict[str, str | int] | None = None
    ) -> ApiFootballAuditResponse:
        """Capture and validate one response while enforcing the local audit ceiling."""

        if self._settings.api_football_key is None:
            raise MissingApiFootballCredentialError(
                "API_FOOTBALL_KEY is not configured; no requests were made"
            )
        if self._request_count >= self._max_requests:
            raise ApiFootballAuditBudgetError(
                f"API-Football audit request limit of {self._max_requests} reached"
            )
        self._request_count += 1
        fetched_at = datetime.now(UTC)
        response = await self._client.get(endpoint, params=params)
        stored = self._raw_store.store(
            provider="apifootball", body=response.content, fetched_at=fetched_at
        )
        try:
            envelope = ApiFootballEnvelope.model_validate_json(response.content)
        except ValidationError as error:
            raise ApiFootballContractError("API-Football returned an invalid envelope") from error
        return ApiFootballAuditResponse(
            status_code=response.status_code,
            envelope=envelope,
            rate_window=ApiFootballRateWindow(
                daily_limit=_integer_header(response.headers, "x-ratelimit-requests-limit"),
                daily_remaining=_integer_header(response.headers, "x-ratelimit-requests-remaining"),
                minute_limit=_integer_header(response.headers, "x-ratelimit-limit"),
                minute_remaining=_integer_header(response.headers, "x-ratelimit-remaining"),
            ),
            raw_object_key=stored.object_key,
            raw_checksum=stored.checksum,
        )
