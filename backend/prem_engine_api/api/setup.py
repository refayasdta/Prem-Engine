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
from prem_engine_api.domain.models import LocalInstallation, Match, ProviderRequest

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupStatusResponse(BaseModel):
    deployment_mode: str
    installation_uuid: UUID | None
    state: Literal["setup_required", "awaiting_sync", "current", "stale"]
    provider_configured: bool
    fixture_count: int
    last_fixture_sync_at: datetime | None
    freshness_limit_seconds: int
    data_current: bool


async def build_setup_status(
    session: AsyncSession, *, settings: Settings, now: datetime
) -> SetupStatusResponse:
    installation_uuid = await session.scalar(select(LocalInstallation.installation_uuid).limit(1))
    fixture_count = int(await session.scalar(select(func.count(Match.match_uuid))) or 0)
    last_sync = await session.scalar(
        select(func.max(ProviderRequest.completed_at)).where(
            ProviderRequest.provider == "kickoffapi",
            ProviderRequest.endpoint == "/api/v2/fixtures",
            ProviderRequest.status == ProviderRequestStatus.SUCCEEDED,
        )
    )
    data_current = bool(
        last_sync is not None
        and (now - last_sync).total_seconds() <= settings.local_fixture_freshness_seconds
    )
    provider_configured = settings.kickoff_api_key is not None
    if data_current:
        state: Literal["setup_required", "awaiting_sync", "current", "stale"] = "current"
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
