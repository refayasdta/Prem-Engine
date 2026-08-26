"""Local installation setup and data-freshness status."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.config import Settings, get_settings
from prem_engine_api.db.dependencies import get_db_session
from prem_engine_api.domain.enums import ProviderRequestStatus
from prem_engine_api.domain.models import (
    LocalInstallation,
    LocalWorkerState,
    Match,
    ProviderRequest,
)

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupStatusResponse(BaseModel):
    deployment_mode: str
    installation_uuid: UUID | None
    state: Literal["setup_required", "awaiting_sync", "syncing", "current", "stale"]
    provider_configured: bool
    fixture_count: int
    last_fixture_sync_at: datetime | None
    freshness_limit_seconds: int
    data_current: bool
    sync_status: str | None
    sync_operation: str | None
    sync_pages_processed: int
    sync_records_received: int
    last_sync_error_code: str | None
    next_fixture_sync_at: datetime | None
    last_player_sync_at: datetime | None


async def build_setup_status(
    session: AsyncSession, *, settings: Settings, now: datetime
) -> SetupStatusResponse:
    installation_uuid = await session.scalar(select(LocalInstallation.installation_uuid).limit(1))
    fixture_count = int(await session.scalar(select(func.count(Match.match_uuid))) or 0)
    worker_state = await session.scalar(
        select(LocalWorkerState).where(LocalWorkerState.singleton_key == 1)
    )
    ledger_last_sync = await session.scalar(
        select(func.max(ProviderRequest.completed_at)).where(
            ProviderRequest.provider == "kickoffapi",
            ProviderRequest.endpoint == "/api/v2/fixtures",
            ProviderRequest.status == ProviderRequestStatus.SUCCEEDED,
        )
    )
    last_sync = (
        worker_state.last_fixture_success_at if worker_state is not None else ledger_last_sync
    )
    data_current = bool(
        last_sync is not None
        and (now - last_sync).total_seconds() <= settings.local_fixture_freshness_seconds
    )
    provider_configured = settings.kickoff_api_key is not None
    if data_current:
        state: Literal["setup_required", "awaiting_sync", "syncing", "current", "stale"] = "current"
    elif worker_state is not None and worker_state.status == "syncing":
        state = "syncing"
    elif fixture_count > 0:
        state = "stale"
    elif provider_configured:
        state = "awaiting_sync"
    else:
        state = "setup_required"
    return SetupStatusResponse(
        deployment_mode=settings.deployment_mode,
        installation_uuid=installation_uuid,
        state=state,
        provider_configured=provider_configured,
        fixture_count=fixture_count,
        last_fixture_sync_at=last_sync,
        freshness_limit_seconds=settings.local_fixture_freshness_seconds,
        data_current=data_current,
        sync_status=worker_state.status if worker_state is not None else None,
        sync_operation=worker_state.current_operation if worker_state is not None else None,
        sync_pages_processed=worker_state.pages_processed if worker_state is not None else 0,
        sync_records_received=worker_state.records_received if worker_state is not None else 0,
        last_sync_error_code=worker_state.last_error_code if worker_state is not None else None,
        next_fixture_sync_at=(
            worker_state.next_fixture_sync_at if worker_state is not None else None
        ),
        last_player_sync_at=worker_state.last_player_sync_at if worker_state is not None else None,
    )


@router.get("/status", response_model=SetupStatusResponse)
async def setup_status(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SetupStatusResponse:
    return await build_setup_status(
        session,
        settings=get_settings(),
        now=datetime.now(UTC),
    )
