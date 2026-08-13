"""FastAPI application entry point."""

import asyncio
from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.api.forecasts import router as forecast_router
from prem_engine_api.api.insights import router as insights_router
from prem_engine_api.config import get_settings
from prem_engine_api.db.dependencies import get_db_session
from prem_engine_api.observability import RequestLoggingMiddleware, configure_observability
from prem_engine_api.origin_auth import OriginAuthenticationMiddleware
from prem_engine_api.rate_limit import RateLimitMiddleware


class HealthResponse(BaseModel):
    """Stable health-check response used by hosting and tests."""

    status: Literal["ok"]
    service: str
    environment: str


class ReadinessResponse(BaseModel):
    """Database-aware readiness result used by the Cloud Run startup boundary."""

    status: Literal["ready", "unavailable"]
    service: str
    environment: str


def create_app() -> FastAPI:
    """Create an application instance without performing network or database I/O."""

    settings = get_settings()
    configure_observability(settings, service="prem-engine-api")
    production = settings.app_env.casefold() == "production"
    app = FastAPI(
        title="Prem Engine API",
        description="Forecast, simulation, standings, and evaluation API.",
        version="0.1.0",
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    if settings.api_rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            limit=settings.api_rate_limit_requests,
            window_seconds=settings.api_rate_limit_window_seconds,
        )
    if settings.api_origin_auth_enabled:
        origin_token = settings.api_origin_token
        if origin_token is None:  # pragma: no cover - enforced by Settings validation
            raise RuntimeError("origin authentication is missing its active token")
        tokens = [origin_token.get_secret_value()]
        if settings.api_origin_token_previous is not None:
            tokens.append(settings.api_origin_token_previous.get_secret_value())
        app.add_middleware(OriginAuthenticationMiddleware, tokens=tuple(tokens))
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(forecast_router)
    app.include_router(insights_router)

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="prem-engine-api",
            environment=settings.app_env,
        )

    @app.get("/ready", response_model=None, tags=["operations"])
    async def ready(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> ReadinessResponse | JSONResponse:
        try:
            async with asyncio.timeout(settings.database_readiness_timeout_seconds):
                await session.execute(text("SELECT 1"))
        except (TimeoutError, SQLAlchemyError):
            return JSONResponse(
                ReadinessResponse(
                    status="unavailable",
                    service="prem-engine-api",
                    environment=settings.app_env,
                ).model_dump(),
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        return ReadinessResponse(
            status="ready",
            service="prem-engine-api",
            environment=settings.app_env,
        )

    return app


app = create_app()
