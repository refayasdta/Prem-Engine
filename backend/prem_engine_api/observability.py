"""Structured operational logging and request correlation."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from prem_engine_api.config import Settings

logger = structlog.get_logger()

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def configure_observability(settings: Settings, *, service: str) -> None:
    """Configure one-line JSON events suitable for Cloud Logging ingestion."""

    level = _LOG_LEVELS.get(settings.log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        environment=settings.app_env,
        service=service,
    )


def _request_id(value: str | None) -> str:
    if value is not None and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid4())


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Return and log a safe correlation ID without recording headers or query values."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _request_id(request.headers.get("x-request-id"))
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "http_request_failed",
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                    method=request.method,
                    path=request.url.path,
                )
                raise
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "http_request_complete",
                duration_ms=round((perf_counter() - started) * 1000, 2),
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )
            return response
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
