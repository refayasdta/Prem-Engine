from fastapi.testclient import TestClient
from prem_engine_api.main import create_app


def test_health_endpoint_reports_service_state() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "prem-engine-api",
        "environment": "development",
    }
