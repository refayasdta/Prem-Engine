"""Audited, tightly-budgeted client for the official FPL bootstrap snapshot."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import ProviderRequestStatus
from prem_engine_api.domain.models import ProviderRequest, RawFetch
from prem_engine_api.domain.request_budget import reserve_request_slot
from prem_engine_api.providers.current_fpl.contracts import CurrentFplBootstrap
from prem_engine_api.providers.kickoffapi.client import (
    CapturedProviderResponse,
    ProviderContractError,
)
from prem_engine_api.providers.raw_storage import RawResponseStorageError, RawResponseStore

PROVIDER = "fpl-current"
SCHEMA_VERSION = "fpl-bootstrap-static-2026-08"


class CurrentFplClient:
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
            base_url=settings.fpl_current_base_url.rstrip("/"), timeout=20, follow_redirects=False
        )

    async def __aenter__(self) -> CurrentFplClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def get_bootstrap(self) -> CapturedProviderResponse:
        endpoint = "/api/bootstrap-static/"
        request_uuid = uuid4()
        async with self._session_factory() as session, session.begin():
            await reserve_request_slot(
                session,
                provider=PROVIDER,
                budget_date=datetime.now(UTC).date(),
                operational_limit=self._settings.fpl_current_operational_request_limit,
                hard_limit=self._settings.fpl_current_daily_request_limit,
            )
            session.add(
                ProviderRequest(
                    provider_request_uuid=request_uuid,
                    provider=PROVIDER,
                    endpoint=endpoint,
                    query_parameters={},
                    status=ProviderRequestStatus.RESERVED,
                )
            )
        try:
            response = await self._http_client.get(
                endpoint,
                headers={
                    "accept": "application/json",
                    "user-agent": "Prem-Engine/1.0 (local squad fallback)",
                },
            )
        except httpx.HTTPError as error:
            await self._fail(request_uuid, type(error).__name__)
            raise
        fetched_at = datetime.now(UTC)
        try:
            stored = self._raw_store.store(
                provider=PROVIDER, body=response.content, fetched_at=fetched_at
            )
        except (OSError, RawResponseStorageError):
            await self._fail(request_uuid, "raw_storage_failed")
            raise
        raw_fetch_uuid = uuid4()
        successful = 200 <= response.status_code < 300
        async with self._session_factory() as session, session.begin():
            ledger = await session.get(ProviderRequest, request_uuid, with_for_update=True)
            if ledger is None:
                raise RuntimeError("provider request ledger row disappeared")
            ledger.status = (
                ProviderRequestStatus.SUCCEEDED if successful else ProviderRequestStatus.FAILED
            )
            ledger.completed_at = fetched_at
            ledger.response_status = response.status_code
            ledger.error_code = None if successful else f"http_{response.status_code}"
            session.add(
                RawFetch(
                    raw_fetch_uuid=raw_fetch_uuid,
                    provider_request_uuid=request_uuid,
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
            CurrentFplBootstrap.model_validate(payload)
        except (json.JSONDecodeError, ValueError) as error:
            await self._fail(request_uuid, "invalid_contract")
            raise ProviderContractError("FPL bootstrap response failed validation") from error
        return CapturedProviderResponse(
            provider_request_uuid=request_uuid, raw_fetch_uuid=raw_fetch_uuid, payload=payload
        )

    async def _fail(self, request_uuid: UUID, code: str) -> None:
        async with self._session_factory() as session, session.begin():
            ledger = await session.get(ProviderRequest, request_uuid, with_for_update=True)
            if ledger is not None:
                ledger.status = ProviderRequestStatus.FAILED
                ledger.completed_at = datetime.now(UTC)
                ledger.error_code = code
