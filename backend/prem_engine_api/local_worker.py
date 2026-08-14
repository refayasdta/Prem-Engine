"""Persistent local synchronization and training worker supervisor."""

from __future__ import annotations

import asyncio
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prem_engine_api.config import Settings, get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.domain.models import (
    CompetitionExternalReference,
    LocalWorkerState,
    Season,
)
from prem_engine_api.domain.request_budget import RequestBudgetExhaustedError
from prem_engine_api.ingestion.player_sync import sync_player_context
from prem_engine_api.local_sync import (
    FixtureSyncProgress,
    active_season_start_year,
    synchronize_local_fixtures,
)
from prem_engine_api.local_training import next_training_cutoff, train_next_local_goal_model
from prem_engine_api.observability import configure_observability
from prem_engine_api.providers.kickoffapi.client import (
    KickoffApiClient,
    ProviderContractError,
    ProviderMinuteBudgetExhaustedError,
    ProviderRateWindowExhaustedError,
)
from prem_engine_api.providers.raw_storage import RawResponseStore, create_raw_response_store

READY_FILE = Path("/tmp/prem-engine-worker-ready")
logger = structlog.get_logger()


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"


def _error_code(error: Exception) -> tuple[str, bool]:
    quota_errors = (
        RequestBudgetExhaustedError,
        ProviderMinuteBudgetExhaustedError,
        ProviderRateWindowExhaustedError,
    )
    if isinstance(error, quota_errors):
        return "provider_quota_limited", True
    if isinstance(error, ProviderContractError):
        return "provider_contract_invalid", False
    if isinstance(error, httpx.TimeoutException):
        return "provider_timeout", False
    if isinstance(error, httpx.HTTPStatusError):
        return "provider_http_error", False
    if isinstance(error, httpx.HTTPError):
        return "provider_transport_error", False
    if str(error) == "player_context_partial_failure":
        return "player_context_partial_failure", False
    return "local_worker_operation_failed", False


async def _locked_state(session: AsyncSession) -> LocalWorkerState:
    state = await session.scalar(
        select(LocalWorkerState)
        .where(LocalWorkerState.singleton_key == 1)
        .with_for_update()
    )
    if state is None:
        state = LocalWorkerState(singleton_key=1, status="idle")
        session.add(state)
        await session.flush()
    return state


def _lease_is_active(state: LocalWorkerState, now: datetime) -> bool:
    return state.lease_expires_at is not None and state.lease_expires_at > now


async def _mark_setup_required(
    sessions: async_sessionmaker[AsyncSession], *, now: datetime
) -> None:
    async with sessions.begin() as session:
        state = await _locked_state(session)
        if not _lease_is_active(state, now):
            state.status = "setup_required"
            state.current_operation = None
            state.lease_owner = None
            state.lease_expires_at = None


async def _claim_fixture_sync(
    sessions: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    worker_id: str,
    now: datetime,
) -> bool | None:
    async with sessions.begin() as session:
        state = await _locked_state(session)
        if _lease_is_active(state, now):
            return None
        if state.next_fixture_sync_at is not None and state.next_fixture_sync_at > now:
            return None
        full = state.last_full_fixture_sync_at is None or (
            now - state.last_full_fixture_sync_at
        ).total_seconds() >= settings.local_full_fixture_sync_interval_seconds
        state.status = "syncing"
        state.current_operation = "fixture_full" if full else "fixture_incremental"
        state.lease_owner = worker_id
        state.lease_expires_at = now + timedelta(seconds=settings.local_worker_lease_seconds)
        state.last_fixture_started_at = now
        state.last_error_code = None
        state.pages_processed = 0
        state.records_received = 0
        state.records_created = 0
        state.records_updated = 0
        state.records_unchanged = 0
        state.records_pending_review = 0
        return full


async def _record_progress(
    sessions: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    worker_id: str,
    progress: FixtureSyncProgress,
) -> None:
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        state = await _locked_state(session)
        if state.lease_owner != worker_id:
            raise RuntimeError("local worker lost its synchronization lease")
        state.lease_expires_at = now + timedelta(seconds=settings.local_worker_lease_seconds)
        state.pages_processed = progress.pages_processed
        state.records_received = progress.records_received
        state.records_created = progress.records_created
        state.records_updated = progress.records_updated
        state.records_unchanged = progress.records_unchanged
        state.records_pending_review = progress.records_pending_review


async def _finish_fixture_sync(
    sessions: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    worker_id: str,
    now: datetime,
    full: bool,
) -> None:
    async with sessions.begin() as session:
        state = await _locked_state(session)
        if state.lease_owner != worker_id:
            raise RuntimeError("local worker lost its synchronization lease")
        state.status = "idle"
        state.current_operation = None
        state.lease_owner = None
        state.lease_expires_at = None
        state.last_fixture_success_at = now
        if full:
            state.last_full_fixture_sync_at = now
        state.next_fixture_sync_at = now + timedelta(
            seconds=settings.local_fixture_sync_interval_seconds
        )
        state.last_error_code = None
        state.last_error_at = None
        if settings.local_goal_training_enabled:
            state.next_training_at = now


async def _claim_player_sync(
    sessions: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    worker_id: str,
    now: datetime,
) -> bool:
    async with sessions.begin() as session:
        state = await _locked_state(session)
        if _lease_is_active(state, now):
            return False
        if state.next_player_sync_at is not None and state.next_player_sync_at > now:
            return False
        if state.last_fixture_success_at is None:
            return False
        state.status = "syncing"
        state.current_operation = "player_context"
        state.lease_owner = worker_id
        state.lease_expires_at = now + timedelta(seconds=settings.local_worker_lease_seconds)
        return True


async def _finish_player_sync(
    sessions: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    worker_id: str,
    now: datetime,
) -> None:
    async with sessions.begin() as session:
        state = await _locked_state(session)
        if state.lease_owner != worker_id:
            raise RuntimeError("local worker lost its player synchronization lease")
        state.status = "idle"
        state.current_operation = None
        state.lease_owner = None
        state.lease_expires_at = None
        state.last_player_sync_at = now
        state.next_player_sync_at = now + timedelta(
            seconds=settings.local_player_sync_interval_seconds
        )
        state.last_error_code = None
        state.last_error_at = None


async def _fail_operation(
    sessions: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    worker_id: str,
    error: Exception,
    now: datetime,
) -> str:
    code, quota_limited = _error_code(error)
    async with sessions.begin() as session:
        state = await _locked_state(session)
        if state.lease_owner == worker_id:
            operation = state.current_operation or "unknown"
            state.status = "quota_limited" if quota_limited else "error"
            state.current_operation = None
            state.lease_owner = None
            state.lease_expires_at = None
            state.last_error_code = f"{operation}:{code}"
            state.last_error_at = now
            if operation.startswith("fixture"):
                state.next_fixture_sync_at = now + timedelta(
                    seconds=settings.local_worker_retry_seconds
                )
            elif operation == "player_context":
                state.next_player_sync_at = now + timedelta(
                    seconds=settings.local_worker_retry_seconds
                )
            elif operation.startswith("goal_training"):
                state.next_training_at = now + timedelta(
                    seconds=settings.local_goal_training_retry_seconds
                )
    return code


async def _release_owned_lease(
    sessions: async_sessionmaker[AsyncSession], *, worker_id: str
) -> None:
    async with sessions.begin() as session:
        state = await _locked_state(session)
        if state.lease_owner == worker_id:
            state.status = "idle"
            state.current_operation = None
            state.lease_owner = None
            state.lease_expires_at = None


async def _season_uuid(
    sessions: async_sessionmaker[AsyncSession], *, settings: Settings, now: datetime
) -> UUID | None:
    season_year = active_season_start_year(now, settings.local_season_start_year)
    label = f"{season_year}/{str(season_year + 1)[-2:]}"
    async with sessions() as session:
        competition_uuid = await session.scalar(
            select(CompetitionExternalReference.competition_uuid).where(
                CompetitionExternalReference.provider == "kickoffapi",
                CompetitionExternalReference.external_competition_id
                == settings.local_competition_code,
            )
        )
        if competition_uuid is None:
            return None
        return cast(
            UUID | None,
            await session.scalar(
                select(Season.season_uuid).where(
                    Season.competition_uuid == competition_uuid,
                    Season.label == label,
                )
            ),
        )


async def _run_fixture_if_due(
    *,
    client: KickoffApiClient,
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    worker_id: str,
    now: datetime,
) -> bool | None:
    full = await _claim_fixture_sync(
        sessions, settings=settings, worker_id=worker_id, now=now
    )
    if full is None:
        return None
    try:
        outcome = await synchronize_local_fixtures(
            client=client,
            session_factory=sessions,
            settings=settings,
            now=now,
            full_season=full,
            progress_callback=lambda progress: _record_progress(
                sessions,
                settings=settings,
                worker_id=worker_id,
                progress=progress,
            ),
        )
        completed_at = datetime.now(UTC)
        await _finish_fixture_sync(
            sessions,
            settings=settings,
            worker_id=worker_id,
            now=completed_at,
            full=full,
        )
        logger.info(
            "local_fixture_sync_complete",
            full_season=full,
            season=outcome.season,
            **outcome.progress.__dict__,
        )
    except Exception as error:
        code = await _fail_operation(
            sessions,
            settings=settings,
            worker_id=worker_id,
            error=error,
            now=datetime.now(UTC),
        )
        logger.exception("local_fixture_sync_failed", error_code=code)
        return False
    return True


async def _claim_training(
    sessions: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    worker_id: str,
    now: datetime,
    matchweek: int,
) -> bool:
    async with sessions.begin() as session:
        state = await _locked_state(session)
        if _lease_is_active(state, now):
            return False
        if state.next_training_at is not None and state.next_training_at > now:
            return False
        state.status = "syncing"
        state.current_operation = f"goal_training_matchweek_{matchweek}"
        state.lease_owner = worker_id
        state.lease_expires_at = now + timedelta(seconds=settings.local_worker_lease_seconds)
        state.last_error_code = None
        return True


async def _defer_training(
    sessions: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    now: datetime,
) -> None:
    async with sessions.begin() as session:
        state = await _locked_state(session)
        if not _lease_is_active(state, now):
            state.next_training_at = now + timedelta(
                seconds=settings.local_fixture_sync_interval_seconds
            )


async def _finish_training(
    sessions: async_sessionmaker[AsyncSession],
    *,
    worker_id: str,
    now: datetime,
) -> None:
    async with sessions.begin() as session:
        state = await _locked_state(session)
        if state.lease_owner != worker_id:
            raise RuntimeError("local worker lost its model-training lease")
        state.status = "idle"
        state.current_operation = None
        state.lease_owner = None
        state.lease_expires_at = None
        state.last_training_at = now
        state.next_training_at = now
        state.last_error_code = None
        state.last_error_at = None


async def _run_training_if_due(
    *,
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    worker_id: str,
    now: datetime,
) -> bool:
    if not settings.local_goal_training_enabled:
        return False
    season_uuid = await _season_uuid(sessions, settings=settings, now=now)
    if season_uuid is None:
        return False
    async with sessions() as session:
        cutoff = await next_training_cutoff(session, season_uuid=season_uuid)
    if cutoff is None:
        await _defer_training(sessions, settings=settings, now=now)
        return False
    if not await _claim_training(
        sessions,
        settings=settings,
        worker_id=worker_id,
        now=now,
        matchweek=cutoff.matchweek,
    ):
        return False
    try:
        outcome = await train_next_local_goal_model(
            sessions,
            settings=settings,
            season_uuid=season_uuid,
            now=now,
        )
        if outcome is None:
            raise RuntimeError("eligible goal-training cutoff disappeared")
        await _finish_training(sessions, worker_id=worker_id, now=datetime.now(UTC))
        logger.info(
            "local_goal_training_complete",
            model_version=outcome.model_version,
            matchweek=outcome.cutoff_matchweek,
            dataset_rows=outcome.dataset_rows,
        )
    except Exception as error:
        code = await _fail_operation(
            sessions,
            settings=settings,
            worker_id=worker_id,
            error=error,
            now=datetime.now(UTC),
        )
        logger.exception("local_goal_training_failed", error_code=code)
    return True


async def _run_player_if_due(
    *,
    client: KickoffApiClient,
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    worker_id: str,
    now: datetime,
) -> bool:
    if not await _claim_player_sync(
        sessions, settings=settings, worker_id=worker_id, now=now
    ):
        return False
    try:
        season_uuid = await _season_uuid(sessions, settings=settings, now=now)
        if season_uuid is None:
            raise RuntimeError("canonical active season is unavailable")
        season_year = active_season_start_year(now, settings.local_season_start_year)
        outcome = await sync_player_context(
            client=client,
            session_factory=sessions,
            season_uuid=season_uuid,
            league=settings.local_competition_code,
            season=season_year,
            max_requests=settings.local_player_sync_max_requests,
            max_squads=settings.local_player_sync_max_squads,
            max_matches=settings.local_player_sync_max_matches,
        )
        if outcome.requests_failed:
            raise RuntimeError("player_context_partial_failure")
        completed_at = datetime.now(UTC)
        await _finish_player_sync(
            sessions,
            settings=settings,
            worker_id=worker_id,
            now=completed_at,
        )
        logger.info(
            "local_player_sync_complete",
            requests_used=outcome.requests_used,
            squads_requested=outcome.squads_requested,
            matches_requested=outcome.matches_requested,
        )
    except Exception as error:
        code = await _fail_operation(
            sessions,
            settings=settings,
            worker_id=worker_id,
            error=error,
            now=datetime.now(UTC),
        )
        logger.exception("local_player_sync_failed", error_code=code)
    return True


async def run() -> None:
    settings = get_settings()
    configure_observability(settings, service="prem-engine-local-worker")
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    raw_store: RawResponseStore | None = None
    worker_id = _worker_id()
    try:
        async with sessions() as session:
            await session.execute(text("SELECT 1"))
        READY_FILE.touch()
        if settings.kickoff_api_key is None:
            await _mark_setup_required(sessions, now=datetime.now(UTC))
            logger.info(
                "local_worker_ready",
                provider_configured=False,
                scheduling_state="setup_required",
            )
            while True:
                await asyncio.sleep(settings.local_worker_heartbeat_seconds)

        raw_store = create_raw_response_store(settings)
        logger.info(
            "local_worker_ready",
            provider_configured=True,
            scheduling_state="active",
        )
        async with KickoffApiClient(
            settings=settings,
            session_factory=sessions,
            raw_store=raw_store,
        ) as client:
            while True:
                now = datetime.now(UTC)
                fixture_result = await _run_fixture_if_due(
                    client=client,
                    sessions=sessions,
                    settings=settings,
                    worker_id=worker_id,
                    now=now,
                )
                if fixture_result is not None:
                    now = datetime.now(UTC)
                if fixture_result is not False:
                    ran_training = await _run_training_if_due(
                        sessions=sessions,
                        settings=settings,
                        worker_id=worker_id,
                        now=now,
                    )
                    if not ran_training:
                        await _run_player_if_due(
                            client=client,
                            sessions=sessions,
                            settings=settings,
                            worker_id=worker_id,
                            now=now,
                        )
                await asyncio.sleep(settings.local_worker_heartbeat_seconds)
    finally:
        READY_FILE.unlink(missing_ok=True)
        if raw_store is not None:
            raw_store.close()
        await _release_owned_lease(sessions, worker_id=worker_id)
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
