"""FastAPI application entry point."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from prem_engine_api.config import get_settings


class HealthResponse(BaseModel):
    """Stable health-check response used by hosting and tests."""

    status: Literal["ok"]
    service: str
    environment: str


def create_app() -> FastAPI:
    """Create an application instance without performing network or database I/O."""

    settings = get_settings()
    app = FastAPI(
        title="Prem Engine API",
        description="Forecast, simulation, standings, and evaluation API.",
        version="0.1.0",
    )

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="prem-engine-api",
            environment=settings.app_env,
        )

    return app


app = create_app()
