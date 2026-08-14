"""Persistent worker leases and operation orchestration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from prem_engine_api import local_worker
from prem_engine_api.config import Settings
from prem_engine_api.domain.models import LocalWorkerState
from prem_engine_api.domain.request_budget import RequestBudgetExhaustedError
from prem_engine_api.ingestion.player_sync import PlayerContextSyncOutcome
from prem_engine_api.local_sync import FixtureSyncProgress, LocalFixtureSyncOutcome
from prem_engine_api.local_training import LocalTrainingOutcome, TrainingCutoff
from prem_engine_api.providers.kickoffapi.client import (
    ProviderContractError,
    ProviderMinuteBudgetExhaustedError,
    ProviderRateWindowExhaustedError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _sessions(
    db_session: AsyncSession,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=await db_session.connection(), expire_on_commit=False)


@pytest.mark.asyncio
async def test_worker_lease_progress_success_and_quota_failure(
    db_session: AsyncSession,
) -> None:
    sessions = await _sessions(db_session)
    settings = Settings(
        local_fixture_sync_interval_seconds=60,
        local_player_sync_interval_seconds=60,
        local_worker_lease_seconds=30,
        local_worker_retry_seconds=10,
    )
    now = datetime(2026, 8, 14, 12, tzinfo=UTC)
    worker_id = "test-worker"

    full = await local_worker._claim_fixture_sync(
        sessions, settings=settings, worker_id=worker_id, now=now
    )
    duplicate = await local_worker._claim_fixture_sync(
        sessions, settings=settings, worker_id="other-worker", now=now
    )
    assert full is True
    assert duplicate is None

    progress = FixtureSyncProgress(
        pages_processed=2,
        records_received=80,
        records_created=70,
        records_updated=5,
        records_unchanged=4,
        records_pending_review=1,
    )
    await local_worker._record_progress(
        sessions,
        settings=settings,
        worker_id=worker_id,
        progress=progress,
    )
    completed = now + timedelta(seconds=2)
    await local_worker._finish_fixture_sync(
        sessions,
        settings=settings,
        worker_id=worker_id,
        now=completed,
        full=True,
    )

    assert await local_worker._claim_player_sync(
        sessions,
        settings=settings,
        worker_id=worker_id,
        now=completed,
    )
    await local_worker._finish_player_sync(
        sessions,
        settings=settings,
        worker_id=worker_id,
        now=completed + timedelta(seconds=1),
    )
    assert await local_worker._claim_training(
        sessions,
        settings=settings,
        worker_id=worker_id,
        now=completed + timedelta(seconds=2),
        matchweek=1,
    )
    await local_worker._finish_training(
        sessions,
        worker_id=worker_id,
        now=completed + timedelta(seconds=3),
    )

    async with sessions.begin() as session:
        state = await session.scalar(
            select(LocalWorkerState)
            .where(LocalWorkerState.singleton_key == 1)
            .with_for_update()
        )
        assert state is not None
        state.next_player_sync_at = None
    assert await local_worker._claim_player_sync(
        sessions,
        settings=settings,
        worker_id=worker_id,
        now=completed + timedelta(seconds=4),
    )
    code = await local_worker._fail_operation(
        sessions,
        settings=settings,
        worker_id=worker_id,
        error=RequestBudgetExhaustedError("bounded test quota"),
        now=completed + timedelta(seconds=5),
    )
    assert code == "provider_quota_limited"

    async with sessions() as session:
        state = await session.scalar(select(LocalWorkerState))
        assert state is not None
        assert state.status == "quota_limited"
        assert state.pages_processed == 2
        assert state.records_received == 80
        assert state.last_error_code == "player_context:provider_quota_limited"


@pytest.mark.asyncio
async def test_fixture_player_and_training_runners_cover_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    settings = Settings()
    sessions = await _sessions(db_session)
    worker_id = "runner-test"
    now = datetime(2026, 8, 14, 12, tzinfo=UTC)
    season_uuid = uuid4()
    fixture_outcome = LocalFixtureSyncOutcome(
        full_season=True,
        season=2026,
        progress=FixtureSyncProgress(pages_processed=1, records_received=1),
        provider_request_uuids=(uuid4(),),
        raw_fetch_uuids=(uuid4(),),
    )
    monkeypatch.setattr(local_worker, "_claim_fixture_sync", AsyncMock(return_value=True))
    monkeypatch.setattr(
        local_worker, "synchronize_local_fixtures", AsyncMock(return_value=fixture_outcome)
    )
    finish_fixture = AsyncMock()
    monkeypatch.setattr(local_worker, "_finish_fixture_sync", finish_fixture)

    fixture_result = await local_worker._run_fixture_if_due(
        client=SimpleNamespace(),  # type: ignore[arg-type]
        sessions=sessions,
        settings=settings,
        worker_id=worker_id,
        now=now,
    )
    assert fixture_result is True
    finish_fixture.assert_awaited_once()

    monkeypatch.setattr(local_worker, "_claim_player_sync", AsyncMock(return_value=True))
    monkeypatch.setattr(local_worker, "_season_uuid", AsyncMock(return_value=season_uuid))
    monkeypatch.setattr(
        local_worker,
        "sync_player_context",
        AsyncMock(
            return_value=PlayerContextSyncOutcome(
                requests_used=2,
                requests_failed=0,
                squads_requested=1,
                matches_requested=1,
                summaries=(),
            )
        ),
    )
    finish_player = AsyncMock()
    monkeypatch.setattr(local_worker, "_finish_player_sync", finish_player)
    assert await local_worker._run_player_if_due(
        client=SimpleNamespace(),  # type: ignore[arg-type]
        sessions=sessions,
        settings=settings,
        worker_id=worker_id,
        now=now,
    )
    finish_player.assert_awaited_once()

    cutoff = TrainingCutoff(
        season_uuid=season_uuid,
        season_label="2026/27",
        matchweek=1,
        revision=1,
        cutoff_at=now,
        fixture_uuids=(str(uuid4()),),
    )
    monkeypatch.setattr(local_worker, "next_training_cutoff", AsyncMock(return_value=cutoff))
    monkeypatch.setattr(local_worker, "_claim_training", AsyncMock(return_value=True))
    monkeypatch.setattr(
        local_worker,
        "train_next_local_goal_model",
        AsyncMock(
            return_value=LocalTrainingOutcome(
                artifact_uuid=uuid4(),
                model_version="goals-local-test",
                cutoff_matchweek=1,
                dataset_rows=2290,
                model_path=Path("model.joblib"),
            )
        ),
    )
    finish_training = AsyncMock()
    monkeypatch.setattr(local_worker, "_finish_training", finish_training)
    assert await local_worker._run_training_if_due(
        sessions=sessions,
        settings=settings,
        worker_id=worker_id,
        now=now,
    )
    finish_training.assert_awaited_once()

    failure = RuntimeError("fixture failed")
    monkeypatch.setattr(
        local_worker, "synchronize_local_fixtures", AsyncMock(side_effect=failure)
    )
    fail_operation = AsyncMock(return_value="local_worker_operation_failed")
    monkeypatch.setattr(local_worker, "_fail_operation", fail_operation)
    assert (
        await local_worker._run_fixture_if_due(
            client=SimpleNamespace(),  # type: ignore[arg-type]
            sessions=sessions,
            settings=settings,
            worker_id=worker_id,
            now=now,
        )
        is False
    )
    fail_operation.assert_awaited_once()


@pytest.mark.parametrize(
    ("error", "expected", "quota_limited"),
    (
        (RequestBudgetExhaustedError("daily"), "provider_quota_limited", True),
        (ProviderMinuteBudgetExhaustedError("minute"), "provider_quota_limited", True),
        (ProviderRateWindowExhaustedError("window"), "provider_quota_limited", True),
        (ProviderContractError("contract"), "provider_contract_invalid", False),
        (httpx.TimeoutException("timeout"), "provider_timeout", False),
        (httpx.ConnectError("network"), "provider_transport_error", False),
        (RuntimeError("player_context_partial_failure"), "player_context_partial_failure", False),
        (RuntimeError("unknown"), "local_worker_operation_failed", False),
    ),
)
def test_worker_error_codes_are_stable_and_secret_free(
    error: Exception, expected: str, quota_limited: bool
) -> None:
    assert local_worker._error_code(error) == (expected, quota_limited)


@pytest.mark.asyncio
async def test_runner_noop_and_partial_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    sessions = await _sessions(db_session)
    settings = Settings()
    worker_id = "branch-test"
    now = datetime(2026, 8, 14, 12, tzinfo=UTC)
    season_uuid = uuid4()

    monkeypatch.setattr(local_worker, "_claim_fixture_sync", AsyncMock(return_value=None))
    assert (
        await local_worker._run_fixture_if_due(
            client=SimpleNamespace(),  # type: ignore[arg-type]
            sessions=sessions,
            settings=settings,
            worker_id=worker_id,
            now=now,
        )
        is None
    )
    monkeypatch.setattr(local_worker, "_claim_player_sync", AsyncMock(return_value=False))
    assert not await local_worker._run_player_if_due(
        client=SimpleNamespace(),  # type: ignore[arg-type]
        sessions=sessions,
        settings=settings,
        worker_id=worker_id,
        now=now,
    )
    assert not await local_worker._run_training_if_due(
        sessions=sessions,
        settings=Settings(local_goal_training_enabled=False),
        worker_id=worker_id,
        now=now,
    )

    monkeypatch.setattr(local_worker, "_season_uuid", AsyncMock(return_value=None))
    assert not await local_worker._run_training_if_due(
        sessions=sessions,
        settings=settings,
        worker_id=worker_id,
        now=now,
    )
    monkeypatch.setattr(local_worker, "_season_uuid", AsyncMock(return_value=season_uuid))
    monkeypatch.setattr(local_worker, "next_training_cutoff", AsyncMock(return_value=None))
    defer = AsyncMock()
    monkeypatch.setattr(local_worker, "_defer_training", defer)
    assert not await local_worker._run_training_if_due(
        sessions=sessions,
        settings=settings,
        worker_id=worker_id,
        now=now,
    )
    defer.assert_awaited_once()

    cutoff = TrainingCutoff(
        season_uuid=season_uuid,
        season_label="2026/27",
        matchweek=1,
        revision=1,
        cutoff_at=now,
        fixture_uuids=(str(uuid4()),),
    )
    monkeypatch.setattr(local_worker, "next_training_cutoff", AsyncMock(return_value=cutoff))
    claim_training = local_worker._claim_training
    monkeypatch.setattr(local_worker, "_claim_training", AsyncMock(return_value=False))
    assert not await local_worker._run_training_if_due(
        sessions=sessions,
        settings=settings,
        worker_id=worker_id,
        now=now,
    )

    monkeypatch.setattr(local_worker, "_claim_training", claim_training)
    await local_worker._mark_setup_required(sessions, now=now)
    assert await local_worker._claim_training(
        sessions,
        settings=settings,
        worker_id=worker_id,
        now=now,
        matchweek=1,
    )
    await local_worker._release_owned_lease(sessions, worker_id=worker_id)
    async with sessions() as session:
        state = await session.scalar(select(LocalWorkerState))
        assert state is not None
        assert state.status == "idle"
        assert state.lease_owner is None
