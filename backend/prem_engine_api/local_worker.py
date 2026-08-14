"""Long-running local worker supervisor for scheduled local services."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from sqlalchemy import text

from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.observability import configure_observability

READY_FILE = Path("/tmp/prem-engine-worker-ready")
logger = structlog.get_logger()


async def run() -> None:
    settings = get_settings()
    configure_observability(settings, service="prem-engine-local-worker")
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            await session.execute(text("SELECT 1"))
        READY_FILE.touch()
        logger.info(
            "local_worker_ready",
            provider_configured=settings.kickoff_api_key is not None,
            scheduling_state=(
                "foundation_idle" if settings.kickoff_api_key is not None else "setup_required"
            ),
        )
        while True:
            await asyncio.sleep(settings.local_worker_heartbeat_seconds)
    finally:
        READY_FILE.unlink(missing_ok=True)
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
