"""Idempotent initialization for one cloneable local installation."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import func, or_, select

from prem_engine_api.config import Settings, get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.domain.models import (
    Competition,
    CompetitionExternalReference,
    LocalInstallation,
    LocalModelArtifact,
    LocalWorkerState,
)
from prem_engine_api.historical.mapping import seed_reviewed_aliases
from prem_engine_api.observability import configure_observability

BOOTSTRAP_VERSION = "local-bootstrap-v1"
logger = structlog.get_logger()


@dataclass(frozen=True)
class InitializationSummary:
    installation_uuid: str
    created: bool
    provider_configured: bool
    bootstrap_version: str
    goal_model_version: str
    statistics_model_version: str
    reviewed_clubs: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_artifact(path: Path, expected_checksum: str, label: str) -> str:
    if not path.is_file():
        raise RuntimeError(f"{label} artifact is missing: {path}")
    actual = _sha256(path)
    if actual != expected_checksum:
        raise RuntimeError(f"{label} artifact checksum does not match configuration")
    return path.parent.name


async def initialize(settings: Settings) -> InitializationSummary:
    goal_version = _verify_artifact(
        settings.goal_model_path, settings.goal_model_sha256, "Phase 7 goal model"
    )
    statistics_version = _verify_artifact(
        settings.statistics_model_path,
        settings.statistics_model_sha256,
        "Phase 12 statistics model",
    )
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            active_goal = await session.scalar(
                select(LocalModelArtifact).where(
                    LocalModelArtifact.model_type == "dynamic_poisson_dixon_coles",
                    LocalModelArtifact.status == "succeeded",
                    LocalModelArtifact.active.is_(True),
                )
            )
            effective_goal_version = goal_version
            effective_goal_checksum = settings.goal_model_sha256
            if active_goal is not None and active_goal.model_checksum is not None:
                effective_goal_version = active_goal.model_version
                effective_goal_checksum = active_goal.model_checksum
            installation = await session.scalar(
                select(LocalInstallation).where(LocalInstallation.singleton_key == 1)
            )
            created = installation is None
            if installation is None:
                installation = LocalInstallation(
                    singleton_key=1,
                    bootstrap_version=BOOTSTRAP_VERSION,
                    goal_model_version=effective_goal_version,
                    goal_model_sha256=effective_goal_checksum,
                    statistics_model_version=statistics_version,
                    statistics_model_sha256=settings.statistics_model_sha256,
                )
                session.add(installation)
                await session.flush()
            else:
                installation.bootstrap_version = BOOTSTRAP_VERSION
                installation.goal_model_version = effective_goal_version
                installation.goal_model_sha256 = effective_goal_checksum
                installation.statistics_model_version = statistics_version
                installation.statistics_model_sha256 = settings.statistics_model_sha256

            worker_state = await session.scalar(
                select(LocalWorkerState).where(LocalWorkerState.singleton_key == 1)
            )
            if worker_state is None:
                session.add(LocalWorkerState(singleton_key=1, status="idle"))

            reference = await session.scalar(
                select(CompetitionExternalReference).where(
                    CompetitionExternalReference.provider == "kickoffapi",
                    CompetitionExternalReference.external_competition_id
                    == settings.local_competition_code,
                )
            )
            competition = (
                await session.get(Competition, reference.competition_uuid)
                if reference is not None
                else await session.scalar(
                    select(Competition).where(
                        or_(
                            Competition.slug == "premier-league",
                            func.lower(Competition.name)
                            == settings.local_competition_name.casefold(),
                        )
                    )
                )
            )
            if competition is None:
                competition = Competition(
                    slug="premier-league",
                    name=settings.local_competition_name,
                    country_code="GB",
                )
                session.add(competition)
                await session.flush()
            if reference is None:
                session.add(
                    CompetitionExternalReference(
                        competition_uuid=competition.competition_uuid,
                        provider="kickoffapi",
                        external_competition_id=settings.local_competition_code,
                        observed_from=datetime.now(UTC),
                    )
                )
            clubs = await seed_reviewed_aliases(
                session,
                provider="football-data",
                registry_path=Path("data/mappings/football-data-clubs.csv"),
            )
        return InitializationSummary(
            installation_uuid=str(installation.installation_uuid),
            created=created,
            provider_configured=settings.kickoff_api_key is not None,
            bootstrap_version=BOOTSTRAP_VERSION,
            goal_model_version=effective_goal_version,
            statistics_model_version=statistics_version,
            reviewed_clubs=len({club.club_uuid for club in clubs.values()}),
        )
    finally:
        await engine.dispose()


async def _run() -> None:
    settings = get_settings()
    configure_observability(settings, service="prem-engine-local-init")
    summary = await initialize(settings)
    logger.info("local_initialization_complete", **asdict(summary))


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
