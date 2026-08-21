"""Local runtime configuration, bootstrap, and setup-state tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from prem_engine_api.api.setup import build_setup_status
from prem_engine_api.config import Settings
from prem_engine_api.local_init import _verify_artifact
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


def test_local_configuration_has_no_hosted_delivery_paths() -> None:
    settings = Settings(deployment_mode="local", kickoff_api_key=None)

    assert settings.local_fixture_freshness_seconds == 14400
    assert settings.kickoff_api_key is None
    assert "forecast_task_scheduling_enabled" not in Settings.model_fields
    assert "public_snapshot_store" not in Settings.model_fields


def test_local_configuration_accepts_an_optional_provider_key() -> None:
    settings = Settings(deployment_mode="local", kickoff_api_key=SecretStr("local-user-key"))

    assert settings.kickoff_api_key is not None
    assert settings.kickoff_api_key.get_secret_value() == "local-user-key"


def test_bootstrap_artifact_verification_is_checksum_pinned(tmp_path: Path) -> None:
    root = tmp_path / "goals-v1-test"
    root.mkdir()
    artifact = root / "model.joblib"
    artifact.write_bytes(b"approved-model")

    assert (
        _verify_artifact(
            artifact,
            "d347103704f78c0256a6a968a8ee0ee38800ddbccef38b7a54dc7745b1aef2d7",
            "test",
        )
        == "goals-v1-test"
    )
    with pytest.raises(RuntimeError, match="checksum"):
        _verify_artifact(artifact, "0" * 64, "test")


@pytest.mark.asyncio
async def test_setup_state_requires_a_key_before_first_sync() -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    missing_session = AsyncMock(spec=AsyncSession)
    missing_session.scalar.side_effect = (None, 0, None, None)
    configured_session = AsyncMock(spec=AsyncSession)
    configured_session.scalar.side_effect = (None, 0, None, None)

    missing_key = await build_setup_status(
        missing_session, settings=Settings(kickoff_api_key=None), now=now
    )
    configured = await build_setup_status(
        configured_session,
        settings=Settings(kickoff_api_key=SecretStr("configured")),
        now=now,
    )

    assert missing_key.state == "setup_required"
    assert missing_key.data_current is False
    assert configured.state == "awaiting_sync"
    assert configured.provider_configured is True


@pytest.mark.asyncio
async def test_setup_state_reports_current_and_stale_fixture_data() -> None:
    now = datetime(2026, 8, 14, 12, tzinfo=UTC)
    current_session = AsyncMock(spec=AsyncSession)
    current_session.scalar.side_effect = (None, 1, None, now - timedelta(minutes=4))
    stale_session = AsyncMock(spec=AsyncSession)
    stale_session.scalar.side_effect = (None, 1, None, now - timedelta(hours=5))

    current = await build_setup_status(current_session, settings=Settings(), now=now)
    stale = await build_setup_status(stale_session, settings=Settings(), now=now)

    assert current.state == "current"
    assert current.data_current is True
    assert stale.state == "stale"
    assert stale.fixture_count == 1


@pytest.mark.asyncio
async def test_setup_state_exposes_active_sync_progress() -> None:
    now = datetime(2026, 8, 14, 12, tzinfo=UTC)
    worker = SimpleNamespace(
        status="syncing",
        current_operation="fixture_full",
        last_fixture_success_at=None,
        pages_processed=3,
        records_received=150,
        last_error_code=None,
        next_fixture_sync_at=None,
        last_player_sync_at=None,
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = (None, 150, worker, None)

    status = await build_setup_status(session, settings=Settings(), now=now)

    assert status.state == "syncing"
    assert status.sync_operation == "fixture_full"
    assert status.sync_pages_processed == 3
    assert status.sync_records_received == 150
