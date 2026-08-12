"""FastAPI application entry point."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from prem_engine_api.api.forecasts import router as forecast_router
from prem_engine_api.api.insights import router as insights_router
from prem_engine_api.config import get_settings
from prem_engine_api.rate_limit import RateLimitMiddleware


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
    if settings.api_rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            limit=settings.api_rate_limit_requests,
            window_seconds=settings.api_rate_limit_window_seconds,
        )
    app.include_router(forecast_router)
    app.include_router(insights_router)

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="prem-engine-api",
            environment=settings.app_env,
        )

    return app


app = create_app()
