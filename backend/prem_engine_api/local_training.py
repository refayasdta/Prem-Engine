"""Chronological, immutable Phase 7 retraining for cloneable local installs."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import joblib  # type: ignore[import-untyped]
from prem_engine_modeling.data import HistoricalDataset, MatchRecord, load_historical_dataset
from prem_engine_modeling.goal_artifacts import (
    GOAL_ARTIFACT_SCHEMA_VERSION,
    load_goal_artifact,
)
from prem_engine_modeling.goal_training import walk_forward_goals
from prem_engine_modeling.goals import GoalModelConfig
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import FixtureStatus
from prem_engine_api.domain.models import (
    ActualResultRevision,
    Club,
    LocalInstallation,
    LocalModelArtifact,
    Match,
    Season,
)
from prem_engine_api.historical.export import export_training_matches

MODEL_TYPE = "dynamic_poisson_dixon_coles"
FEATURE_SCHEMA = (
    "online_home_attack_strength",
    "online_home_defence_strength",
    "online_away_attack_strength",
    "online_away_defence_strength",
    "home_advantage",
    "season_carryover",
)
EXCLUDED_FIXTURE_STATUSES = (FixtureStatus.POSTPONED, FixtureStatus.CANCELLED)


@dataclass(frozen=True)
class TrainingCutoff:
    season_uuid: UUID
    season_label: str
    matchweek: int
    revision: int
    cutoff_at: datetime
    fixture_uuids: tuple[str, ...]


@dataclass(frozen=True)
class LocalTrainingOutcome:
    artifact_uuid: UUID
    model_version: str
    cutoff_matchweek: int
    dataset_rows: int
    model_path: Path


@dataclass(frozen=True)
class _WrittenArtifact:
    version: str
    directory: Path
    model_path: Path
    model_checksum: str
    report_checksum: str


@dataclass(frozen=True)
class _GoalFit:
    dataset: HistoricalDataset
    attack: dict[str, float]
    defence: dict[str, float]
    club_names: dict[str, str]
    strategy: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_versions() -> dict[str, str]:
    values = {"python": platform.python_version()}
    for distribution in ("joblib", "numpy", "scikit-learn", "scipy"):
        try:
            values[distribution] = package_version(distribution)
        except PackageNotFoundError:
            values[distribution] = "not-installed"
    return values


def _result(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


def _dataset_checksum(records: tuple[MatchRecord, ...]) -> str:
    canonical = [
        {
            **asdict(record),
            "kickoff_at": record.kickoff_at.isoformat(),
            "available_after": record.available_after.isoformat(),
        }
        for record in records
    ]
    body = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()


def _fixture_checksum(fixture_uuids: tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(fixture_uuids).encode()).hexdigest()


def _load_baseline_config(path: Path) -> GoalModelConfig:
    payload = joblib.load(path)
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != GOAL_ARTIFACT_SCHEMA_VERSION
    ):
        raise ValueError("baseline Phase 7 artifact contract is invalid")
    raw_config = payload.get("config")
    if not isinstance(raw_config, dict):
        raise ValueError("baseline Phase 7 artifact config is missing")
    return GoalModelConfig(**cast(dict[str, Any], raw_config))


async def next_training_cutoff(
    session: AsyncSession,
    *,
    season_uuid: UUID,
) -> TrainingCutoff | None:
    """Return the first unbuilt eligible cutoff without skipping an unfinished round."""

    matches = list(
        await session.scalars(
            select(Match)
            .where(Match.season_uuid == season_uuid, Match.matchweek.is_not(None))
            .order_by(Match.matchweek, Match.current_kickoff_at, Match.match_uuid)
        )
    )
    if not matches:
        return None
    season = await session.get(Season, season_uuid)
    if season is None:
        return None
    artifacts = list(
        await session.scalars(
            select(LocalModelArtifact)
            .where(
                LocalModelArtifact.model_type == MODEL_TYPE,
                LocalModelArtifact.season_uuid == season_uuid,
                LocalModelArtifact.status == "succeeded",
            )
            .order_by(
                LocalModelArtifact.cutoff_matchweek,
                LocalModelArtifact.cutoff_revision.desc(),
            )
        )
    )
    latest_artifact: dict[int, LocalModelArtifact] = {}
    for artifact in artifacts:
        latest_artifact.setdefault(artifact.cutoff_matchweek, artifact)
    by_matchweek: dict[int, list[Match]] = {}
    for match in matches:
        if match.matchweek is not None:
            by_matchweek.setdefault(match.matchweek, []).append(match)
    for matchweek in sorted(by_matchweek):
        included = [
            match
            for match in by_matchweek[matchweek]
            if match.status not in EXCLUDED_FIXTURE_STATUSES
        ]
        if not included:
            continue
        fixture_ids = [match.match_uuid for match in included]
        result_rows = (
            await session.execute(
                select(ActualResultRevision.match_uuid, ActualResultRevision.observed_at).where(
                    ActualResultRevision.match_uuid.in_(fixture_ids),
                    ActualResultRevision.accepted.is_(True),
                    ActualResultRevision.training_eligible.is_(True),
                )
            )
        ).all()
        result_times = {match_uuid: observed_at for match_uuid, observed_at in result_rows}
        if any(match.match_uuid not in result_times for match in included):
            return None
        prefix_ids = [
            match.match_uuid
            for prefix_matchweek, prefix_matches in by_matchweek.items()
            if prefix_matchweek <= matchweek
            for match in prefix_matches
        ]
        change_at = await session.scalar(
            select(
                func.max(
                    func.coalesce(
                        ActualResultRevision.voided_at,
                        ActualResultRevision.observed_at,
                    )
                )
            ).where(ActualResultRevision.match_uuid.in_(prefix_ids))
        )
        if change_at is None:
            return None
        previous = latest_artifact.get(matchweek)
        if previous is not None and previous.cutoff_at >= change_at:
            continue
        return TrainingCutoff(
            season_uuid=season_uuid,
            season_label=season.label,
            matchweek=matchweek,
            revision=1 if previous is None else previous.cutoff_revision + 1,
            cutoff_at=change_at,
            fixture_uuids=tuple(sorted(str(value) for value in fixture_ids)),
        )
    return None


async def _current_records(
    session: AsyncSession,
    *,
    cutoff: TrainingCutoff,
) -> tuple[MatchRecord, ...]:
    ranked = (
        select(
            ActualResultRevision.actual_result_uuid.label("result_uuid"),
            ActualResultRevision.match_uuid.label("match_uuid"),
            func.row_number()
            .over(
                partition_by=ActualResultRevision.match_uuid,
                order_by=(
                    ActualResultRevision.observed_at.desc(),
                    ActualResultRevision.revision_number.desc(),
                ),
            )
            .label("result_rank"),
        )
        .where(
            ActualResultRevision.observed_at <= cutoff.cutoff_at,
            ActualResultRevision.training_eligible.is_(True),
        )
        .subquery()
    )
    home = aliased(Club)
    away = aliased(Club)
    rows = (
        await session.execute(
            select(Match, ActualResultRevision, home, away)
            .join(
                ranked,
                (ranked.c.match_uuid == Match.match_uuid) & (ranked.c.result_rank == 1),
            )
            .join(
                ActualResultRevision,
                ActualResultRevision.actual_result_uuid == ranked.c.result_uuid,
            )
            .join(home, home.club_uuid == Match.home_club_uuid)
            .join(away, away.club_uuid == Match.away_club_uuid)
            .where(
                Match.season_uuid == cutoff.season_uuid,
                Match.matchweek <= cutoff.matchweek,
                Match.status.not_in(EXCLUDED_FIXTURE_STATUSES),
            )
            .order_by(Match.current_kickoff_at, Match.match_uuid)
        )
    ).all()
    return tuple(
        MatchRecord(
            match_uuid=str(match.match_uuid),
            season=cutoff.season_label,
            kickoff_at=match.current_kickoff_at,
            available_after=actual.observed_at,
            home_club_uuid=str(match.home_club_uuid),
            home_club=home_club.canonical_name,
            away_club_uuid=str(match.away_club_uuid),
            away_club=away_club.canonical_name,
            home_goals=actual.home_goals,
            away_goals=actual.away_goals,
            result=cast(Any, _result(actual.home_goals, actual.away_goals)),
        )
        for match, actual, home_club, away_club in rows
    )


async def _training_dataset(
    session: AsyncSession,
    *,
    cutoff: TrainingCutoff,
) -> HistoricalDataset:
    with tempfile.TemporaryDirectory(prefix="prem-engine-history-") as temporary:
        export_path = Path(temporary) / "training.csv"
        await export_training_matches(session, export_path)
        historical = load_historical_dataset(export_path)
    current = await _current_records(session, cutoff=cutoff)
    records = tuple(
        sorted(
            (*historical.records, *current),
            key=lambda row: (row.kickoff_at, row.match_uuid),
        )
    )
    seasons = historical.seasons
    if current and cutoff.season_label not in seasons:
        seasons = (*seasons, cutoff.season_label)
    return HistoricalDataset(
        records=records,
        checksum=_dataset_checksum(records),
        seasons=seasons,
    )


def _fit_goal_state(
    dataset: HistoricalDataset,
    *,
    cutoff: TrainingCutoff,
    baseline_path: Path,
    config: GoalModelConfig,
) -> _GoalFit:
    """Refit full history when present, otherwise continue the approved baseline snapshot."""

    baseline = load_goal_artifact(baseline_path)
    records = tuple(
        replace(
            record,
            home_club_uuid=baseline.resolve_club_uuid(
                record.home_club_uuid, record.home_club
            ),
            away_club_uuid=baseline.resolve_club_uuid(
                record.away_club_uuid, record.away_club
            ),
        )
        for record in dataset.records
    )
    canonical = HistoricalDataset(
        records=records,
        checksum=_dataset_checksum(records),
        seasons=dataset.seasons,
    )
    club_names = baseline.club_names_snapshot()
    for record in records:
        club_names.setdefault(record.home_club_uuid, record.home_club)
        club_names.setdefault(record.away_club_uuid, record.away_club)

    has_prior_season_history = any(
        record.season != cutoff.season_label for record in records
    )
    if has_prior_season_history:
        output = walk_forward_goals(canonical, config=config, score_seasons=())
        return _GoalFit(
            dataset=canonical,
            attack=output.final_attack,
            defence=output.final_defence,
            club_names=club_names,
            strategy="full_history_refit",
        )

    baseline.begin_season(cutoff.season_label)
    for record in sorted(records, key=lambda item: (item.available_after, item.match_uuid)):
        baseline.update(record)
    return _GoalFit(
        dataset=canonical,
        attack=baseline.attack_snapshot(),
        defence=baseline.defence_snapshot(),
        club_names=club_names,
        strategy="approved_baseline_continuation",
    )


def _model_version(
    dataset: HistoricalDataset,
    *,
    cutoff: TrainingCutoff,
    config: GoalModelConfig,
) -> str:
    identity = {
        "schema": GOAL_ARTIFACT_SCHEMA_VERSION,
        "dataset": dataset.checksum,
        "config": asdict(config),
        "season": cutoff.season_label,
        "matchweek": cutoff.matchweek,
        "revision": cutoff.revision,
        "cutoff_at": cutoff.cutoff_at.isoformat(),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return (
        f"goals-local-v1-mw{cutoff.matchweek:02d}r{cutoff.revision:02d}-{digest[:12]}"
    )


def _write_artifact(
    *,
    settings: Settings,
    cutoff: TrainingCutoff,
    dataset: HistoricalDataset,
    config: GoalModelConfig,
    attack: dict[str, float],
    defence: dict[str, float],
    runtime_versions: dict[str, str],
    created_at: datetime,
    club_names: dict[str, str] | None = None,
    training_strategy: str = "full_history_refit",
) -> _WrittenArtifact:
    artifact_root = settings.local_model_root / "goals"
    artifact_root.mkdir(parents=True, exist_ok=True)
    version = _model_version(dataset, cutoff=cutoff, config=config)
    destination = artifact_root / version
    model_path = destination / "model.joblib"
    report_path = destination / "provenance.json"
    if destination.exists():
        if not model_path.is_file() or not report_path.is_file():
            raise RuntimeError("existing local artifact directory is incomplete")
        return _WrittenArtifact(
            version=version,
            directory=destination,
            model_path=model_path,
            model_checksum=_sha256(model_path),
            report_checksum=_sha256(report_path),
        )

    temporary = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=artifact_root))
    try:
        artifact_club_names = dict(club_names or {})
        for record in dataset.records:
            artifact_club_names.setdefault(record.home_club_uuid, record.home_club)
            artifact_club_names.setdefault(record.away_club_uuid, record.away_club)
        payload: dict[str, Any] = {
            "schema_version": GOAL_ARTIFACT_SCHEMA_VERSION,
            "model_version": version,
            "model_type": MODEL_TYPE,
            "dataset_checksum": dataset.checksum,
            "trained_through": cutoff.cutoff_at.isoformat(),
            "current_season": cutoff.season_label,
            "config": asdict(config),
            "attack": attack,
            "defence": defence,
            "club_names": dict(sorted(artifact_club_names.items())),
            "local_cutoff": {
                "season": cutoff.season_label,
                "matchweek": cutoff.matchweek,
                "revision": cutoff.revision,
                "observed_at": cutoff.cutoff_at.isoformat(),
            },
            "trained_current_fixture_uuids": sorted(
                record.match_uuid
                for record in dataset.records
                if record.season == cutoff.season_label
            ),
        }
        temporary_model = temporary / "model.joblib"
        joblib.dump(payload, temporary_model, compress=3)
        model_checksum = _sha256(temporary_model)
        report = {
            "contract_version": "local-goal-provenance-v1",
            "created_at": created_at.isoformat(),
            "model_version": version,
            "model_type": MODEL_TYPE,
            "outcome": "succeeded",
            "cutoff": payload["local_cutoff"],
            "training_data_checksum": dataset.checksum,
            "training_rows": len(dataset.records),
            "training_strategy": training_strategy,
            "fixture_set_checksum": _fixture_checksum(cutoff.fixture_uuids),
            "included_fixture_uuids": list(cutoff.fixture_uuids),
            "feature_schema": list(FEATURE_SCHEMA),
            "runtime_versions": runtime_versions,
            "config": asdict(config),
            "model_artifact": {"path": "model.joblib", "sha256": model_checksum},
        }
        report_body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
        (temporary / "provenance.json").write_bytes(report_body)
        temporary.rename(destination)
        return _WrittenArtifact(
            version=version,
            directory=destination,
            model_path=destination / "model.joblib",
            model_checksum=model_checksum,
            report_checksum=hashlib.sha256(report_body).hexdigest(),
        )
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


async def train_next_local_goal_model(
    sessions: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    season_uuid: UUID,
    now: datetime | None = None,
) -> LocalTrainingOutcome | None:
    """Refit one eligible matchweek and atomically activate it after verification."""

    started_at = now or datetime.now(UTC)
    async with sessions() as session:
        cutoff = await next_training_cutoff(session, season_uuid=season_uuid)
        if cutoff is None:
            return None
        dataset = await _training_dataset(session, cutoff=cutoff)
    config = _load_baseline_config(settings.goal_model_path)
    fit = _fit_goal_state(
        dataset,
        cutoff=cutoff,
        baseline_path=settings.goal_model_path,
        config=config,
    )
    dataset = fit.dataset
    model_version = _model_version(dataset, cutoff=cutoff, config=config)
    fixture_checksum = _fixture_checksum(cutoff.fixture_uuids)
    runtime_versions = _runtime_versions()

    async with sessions.begin() as session:
        registry = await session.scalar(
            select(LocalModelArtifact)
            .where(
                LocalModelArtifact.model_type == MODEL_TYPE,
                LocalModelArtifact.season_uuid == cutoff.season_uuid,
                LocalModelArtifact.cutoff_matchweek == cutoff.matchweek,
                LocalModelArtifact.cutoff_revision == cutoff.revision,
            )
            .with_for_update()
        )
        if registry is None:
            registry = LocalModelArtifact(
                model_type=MODEL_TYPE,
                model_version=model_version,
                season_uuid=cutoff.season_uuid,
                cutoff_matchweek=cutoff.matchweek,
                cutoff_revision=cutoff.revision,
                cutoff_at=cutoff.cutoff_at,
                status="running",
                active=False,
                training_data_checksum=dataset.checksum,
                fixture_set_checksum=fixture_checksum,
                included_fixture_uuids=list(cutoff.fixture_uuids),
                feature_schema=list(FEATURE_SCHEMA),
                runtime_versions=runtime_versions,
                started_at=started_at,
            )
            session.add(registry)
            await session.flush()
        else:
            registry.model_version = model_version
            registry.cutoff_at = cutoff.cutoff_at
            registry.status = "running"
            registry.active = False
            registry.training_data_checksum = dataset.checksum
            registry.fixture_set_checksum = fixture_checksum
            registry.included_fixture_uuids = list(cutoff.fixture_uuids)
            registry.feature_schema = list(FEATURE_SCHEMA)
            registry.runtime_versions = runtime_versions
            registry.started_at = started_at
            registry.completed_at = None
            registry.error_code = None
        artifact_uuid = registry.artifact_uuid

    try:
        written = _write_artifact(
            settings=settings,
            cutoff=cutoff,
            dataset=dataset,
            config=config,
            attack=fit.attack,
            defence=fit.defence,
            runtime_versions=runtime_versions,
            created_at=started_at,
            club_names=fit.club_names,
            training_strategy=fit.strategy,
        )
    except Exception:
        async with sessions.begin() as session:
            registry = await session.get(LocalModelArtifact, artifact_uuid, with_for_update=True)
            if registry is not None:
                registry.status = "failed"
                registry.active = False
                registry.completed_at = datetime.now(UTC)
                registry.error_code = "goal_training_failed"
        raise

    completed_at = datetime.now(UTC)
    async with sessions.begin() as session:
        await session.execute(
            update(LocalModelArtifact)
            .where(
                LocalModelArtifact.model_type == MODEL_TYPE,
                LocalModelArtifact.active.is_(True),
            )
            .values(active=False)
        )
        registry = await session.get(LocalModelArtifact, artifact_uuid, with_for_update=True)
        if registry is None:
            raise RuntimeError("local model registry entry disappeared")
        registry.status = "succeeded"
        registry.active = True
        registry.artifact_path = str(written.model_path)
        registry.model_checksum = written.model_checksum
        registry.report_checksum = written.report_checksum
        registry.completed_at = completed_at
        registry.error_code = None
        installation = await session.scalar(
            select(LocalInstallation)
            .where(LocalInstallation.singleton_key == 1)
            .with_for_update()
        )
        if installation is not None:
            installation.goal_model_version = written.version
            installation.goal_model_sha256 = written.model_checksum
    return LocalTrainingOutcome(
        artifact_uuid=artifact_uuid,
        model_version=written.version,
        cutoff_matchweek=cutoff.matchweek,
        dataset_rows=len(dataset.records),
        model_path=written.model_path,
    )
