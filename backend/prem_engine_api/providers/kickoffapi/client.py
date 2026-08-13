"""Quota-aware KickoffAPI v2 client with append-only response capture."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import ProviderRequestStatus
from prem_engine_api.domain.models import ProviderRequest, ProviderRequestBudget, RawFetch
from prem_engine_api.domain.request_budget import reserve_request_slot
from prem_engine_api.providers.raw_storage import RawResponseStorageError, RawResponseStore

PROVIDER = "kickoffapi"
SCHEMA_VERSION = "kickoffapi-v2-2026-08"
logger = structlog.get_logger()


class MissingProviderCredentialError(RuntimeError):
    """Raised before a request when no server-side provider key is configured."""


class ProviderContractError(RuntimeError):
    """Raised when a response cannot be decoded as the documented JSON contract."""


class ProviderRateWindowExhaustedError(RuntimeError):
    """Raised locally when the latest provider response reports no remaining calls."""


class ProviderMinuteBudgetExhaustedError(RuntimeError):
    """Raised before exceeding Prem Engine's conservative rolling-minute ceiling."""


@dataclass(frozen=True)
class CapturedProviderResponse:
    provider_request_uuid: UUID
    raw_fetch_uuid: UUID
    payload: Any


def _header_int(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _rate_reset(headers: httpx.Headers) -> datetime | None:
    value = _header_int(headers, "x-ratelimit-reset")
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


class KickoffApiClient:
    """Perform read-only GET requests and persist every attempt and response."""

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        raw_store: RawResponseStore,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._raw_store = raw_store
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            base_url=settings.kickoff_api_base_url.rstrip("/"),
            timeout=20,
            follow_redirects=False,
        )

    async def __aenter__(self) -> KickoffApiClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def get(
        self,
        endpoint: str,
        *,
        params: dict[str, str | int | float | bool] | None = None,
    ) -> CapturedProviderResponse:
        """Reserve quota, execute one GET, and capture the byte-exact response."""

        if self._settings.kickoff_api_key is None:
            raise MissingProviderCredentialError("KICKOFF_API_KEY is not configured")
        safe_params = dict(params or {})
        provider_request_uuid = uuid4()
        quota_warning_count: int | None = None
        async with self._session_factory() as session, session.begin():
            latest_request = await session.scalar(
                select(ProviderRequest)
                .where(ProviderRequest.provider == PROVIDER)
                .order_by(ProviderRequest.requested_at.desc())
                .limit(1)
                .with_for_update()
            )
            now = datetime.now(UTC)
            if (
                latest_request is not None
                and latest_request.rate_remaining is not None
                and latest_request.rate_remaining <= 0
                and (latest_request.rate_reset_at is None or latest_request.rate_reset_at > now)
            ):
                raise ProviderRateWindowExhaustedError(
                    "KickoffAPI reported no remaining requests in the current rate window"
                )
            budget_uuid = await reserve_request_slot(
                session,
                provider=PROVIDER,
                budget_date=datetime.now(UTC).date(),
                operational_limit=self._settings.kickoff_operational_request_limit,
                hard_limit=self._settings.kickoff_daily_request_limit,
            )
            reserved_count = await session.scalar(
                select(ProviderRequestBudget.request_count).where(
                    ProviderRequestBudget.budget_uuid == budget_uuid
                )
            )
            if reserved_count == self._settings.kickoff_quota_warning_threshold:
                quota_warning_count = reserved_count
            recent_request_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ProviderRequest)
                    .where(
                        ProviderRequest.provider == PROVIDER,
                        ProviderRequest.requested_at >= now - timedelta(minutes=1),
                    )
                )
                or 0
            )
            if recent_request_count >= self._settings.kickoff_operational_minute_limit:
                raise ProviderMinuteBudgetExhaustedError(
                    "KickoffAPI operational rolling-minute request limit reached"
                )
            session.add(
                ProviderRequest(
                    provider_request_uuid=provider_request_uuid,
                    provider=PROVIDER,
                    endpoint=endpoint,
                    query_parameters=safe_params,
                    status=ProviderRequestStatus.RESERVED,
                )
            )

        if quota_warning_count is not None:
            logger.warning(
                "provider_quota_approaching",
                provider=PROVIDER,
                request_count=quota_warning_count,
                operational_limit=self._settings.kickoff_operational_request_limit,
                hard_limit=self._settings.kickoff_daily_request_limit,
            )

        try:
            response = await self._http_client.get(
                endpoint,
                params=safe_params,
                headers={
                    "x-api-key": self._settings.kickoff_api_key.get_secret_value(),
                    "accept": "application/json",
                },
            )
        except httpx.HTTPError as error:
            await self._mark_request_failed(provider_request_uuid, type(error).__name__)
            raise

        fetched_at = datetime.now(UTC)
        try:
            stored = self._raw_store.store(
                provider=PROVIDER, body=response.content, fetched_at=fetched_at
            )
        except (OSError, RawResponseStorageError) as error:
            await self._mark_request_failed(provider_request_uuid, "raw_storage_failed")
            logger.exception(
                "raw_response_storage_failed",
                provider=PROVIDER,
                provider_request_uuid=str(provider_request_uuid),
                error_type=type(error).__name__,
            )
            raise
        raw_fetch_uuid = uuid4()
        successful = 200 <= response.status_code < 300
        async with self._session_factory() as session, session.begin():
            request = await session.get(
                ProviderRequest, provider_request_uuid, with_for_update=True
            )
            if request is None:  # pragma: no cover - protected by the reservation transaction
                raise RuntimeError("provider request ledger row disappeared")
            request.status = (
                ProviderRequestStatus.SUCCEEDED if successful else ProviderRequestStatus.FAILED
            )
            request.completed_at = fetched_at
            request.response_status = response.status_code
            request.rate_limit = _header_int(response.headers, "x-ratelimit-limit")
            request.rate_remaining = _header_int(response.headers, "x-ratelimit-remaining")
            request.rate_reset_at = _rate_reset(response.headers)
            request.provider_request_id = response.headers.get("x-request-id")
            request.error_code = None if successful else f"http_{response.status_code}"
            session.add(
                RawFetch(
                    raw_fetch_uuid=raw_fetch_uuid,
                    provider_request_uuid=provider_request_uuid,
                    provider=PROVIDER,
                    endpoint=endpoint,
                    fetched_at=fetched_at,
                    response_status=response.status_code,
                    response_checksum=stored.checksum,
                    object_key=stored.object_key,
                    schema_version=SCHEMA_VERSION,
                )
            )
        response.raise_for_status()
        try:
            payload: Any = response.json()
        except json.JSONDecodeError as error:
            await self._mark_request_failed(provider_request_uuid, "invalid_json")
            raise ProviderContractError("KickoffAPI returned invalid JSON") from error
        return CapturedProviderResponse(
            provider_request_uuid=provider_request_uuid,
            raw_fetch_uuid=raw_fetch_uuid,
            payload=payload,
        )

    async def _mark_request_failed(self, request_uuid: UUID, error_code: str) -> None:
        async with self._session_factory() as session, session.begin():
            request = await session.get(ProviderRequest, request_uuid, with_for_update=True)
            if request is not None:
                request.status = ProviderRequestStatus.FAILED
                request.completed_at = datetime.now(UTC)
                request.error_code = error_code
