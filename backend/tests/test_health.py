from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from prem_engine_api.config import Settings
from prem_engine_api.db.dependencies import get_db_session
from prem_engine_api.main import create_app
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession


def test_health_endpoint_reports_service_state() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "prem-engine-api",
        "environment": "development",
    }
    assert response.headers["x-request-id"]


def test_request_id_is_preserved_when_safe_and_replaced_when_unsafe() -> None:
    client = TestClient(create_app())

    preserved = client.get("/health", headers={"x-request-id": "release-16c.42"})
    replaced = client.get("/health", headers={"x-request-id": "unsafe request id"})

    assert preserved.headers["x-request-id"] == "release-16c.42"
    assert replaced.headers["x-request-id"] != "unsafe request id"
    assert len(replaced.headers["x-request-id"]) == 36


def test_production_origin_auth_is_required_only_for_api_runtime() -> None:
    worker = Settings(
        app_env="production",
        runtime_role="worker",
        database_ssl_required=True,
    )

    assert worker.runtime_role == "worker"
    with pytest.raises(ValueError, match="API_ORIGIN_AUTH_ENABLED"):
        Settings(app_env="production", runtime_role="api", database_ssl_required=True)


def test_readiness_endpoint_checks_database() -> None:
    app = create_app()
    session = AsyncMock(spec=AsyncSession)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = override_session
    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    session.execute.assert_awaited_once()


def test_readiness_endpoint_fails_when_database_is_unavailable() -> None:
    app = create_app()
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("offline"))

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = override_session
    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.headers["cache-control"] == "no-store"


def test_origin_authentication_protects_only_api_routes(monkeypatch: object) -> None:
    import prem_engine_api.main as main_module

    token = "a" * 32
    settings = Settings(
        api_origin_auth_enabled=True,
        api_origin_token=SecretStr(token),
        api_origin_token_previous=SecretStr("b" * 32),
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)  # type: ignore[attr-defined]
    client = TestClient(main_module.create_app())

    assert client.get("/health").status_code == 200
    assert client.get("/api/not-real").status_code == 401
    assert (
        client.get("/api/not-real", headers={"x-prem-engine-origin-token": token}).status_code
        == 404
    )
    assert (
        client.get("/api/not-real", headers={"x-prem-engine-origin-token": "b" * 32}).status_code
        == 404
    )
