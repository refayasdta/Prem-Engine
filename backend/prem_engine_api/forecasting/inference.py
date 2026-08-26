"""Production adapter from canonical database data to approved model artifacts."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import joblib  # type: ignore[import-untyped]
import numpy as np
from prem_engine_modeling.data import MatchRecord
from prem_engine_modeling.features import PREMATCH_FEATURE_COLUMNS
from prem_engine_modeling.goal_artifacts import (
    GOAL_ARTIFACT_SCHEMA_VERSION,
    load_goal_artifact,
)
from prem_engine_modeling.match_statistics_artifacts import load_statistics_artifact
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from prem_engine_api.config import Settings
from prem_engine_api.domain.models import (
    ActualResultRevision,
    Club,
    LocalModelArtifact,
    Match,
    Season,
)
from prem_engine_api.forecasting.contracts import (
    FeatureSnapshotInput,
    ForecastPackage,
    ModelForecast,
)
from prem_engine_api.forecasting.lineups import expected_lineup_for_club


class ArtifactConfigurationError(RuntimeError):
    """Raised when a configured inference artifact is missing or untrusted."""


class ForecastInputUnavailableError(RuntimeError):
    """Raised when current canonical data cannot safely support a forecast."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_path(path: Path, expected_checksum: str, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ArtifactConfigurationError(f"configured {label} artifact does not exist")
    if _sha256(resolved).casefold() != expected_checksum.casefold():
        raise ArtifactConfigurationError(f"configured {label} artifact checksum differs")
    return resolved


def _result(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


class OfficialArtifactForecastFactory:
    """Build a time-safe package using Phase 7 and Phase 12 official artifacts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _goal_artifact(self, session: AsyncSession, *, cutoff: datetime) -> tuple[Path, str]:
        path = self._settings.goal_model_path
        checksum = self._settings.goal_model_sha256
        if self._settings.deployment_mode == "local":
            local = await session.scalar(
                select(LocalModelArtifact)
                .where(
                    LocalModelArtifact.model_type == "dynamic_poisson_dixon_coles",
                    LocalModelArtifact.status == "succeeded",
                    LocalModelArtifact.cutoff_at < cutoff,
                )
                .order_by(
                    LocalModelArtifact.cutoff_at.desc(),
                    LocalModelArtifact.cutoff_revision.desc(),
                )
                .limit(1)
            )
            if local is not None:
                if local.artifact_path is None or local.model_checksum is None:
                    raise ArtifactConfigurationError("active local goal artifact is incomplete")
                path = Path(local.artifact_path)
                checksum = local.model_checksum
        return _verified_path(path, checksum, "goal"), checksum

    async def build(
        self,
        session: AsyncSession,
        *,
        match_uuid: UUID,
        cutoff: datetime,
    ) -> ForecastPackage:
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("forecast cutoff must include a timezone")
        home_club = aliased(Club)
        away_club = aliased(Club)
        row = (
            await session.execute(
                select(Match, Season, home_club, away_club)
                .join(Season, Season.season_uuid == Match.season_uuid)
                .join(home_club, home_club.club_uuid == Match.home_club_uuid)
                .join(away_club, away_club.club_uuid == Match.away_club_uuid)
                .where(Match.match_uuid == match_uuid)
            )
        ).one_or_none()
        if row is None:
            raise ForecastInputUnavailableError("canonical match is missing")
        match, season, home, away = row
        if cutoff != match.prediction_due_at:
            raise ForecastInputUnavailableError("requested cutoff is not the current T-24 time")

        goal_path, goal_checksum = await self._goal_artifact(session, cutoff=cutoff)
        statistics_path = _verified_path(
            self._settings.statistics_model_path,
            self._settings.statistics_model_sha256,
            "statistics",
        )
        raw_goal = joblib.load(goal_path)
        if (
            not isinstance(raw_goal, dict)
            or raw_goal.get("schema_version") != GOAL_ARTIFACT_SCHEMA_VERSION
        ):
            raise ArtifactConfigurationError("configured goal artifact contract is invalid")
        goal_metadata = cast(dict[str, Any], raw_goal)
        outcome_model_version = str(goal_metadata.get("model_version") or "")
        artifact_season = str(goal_metadata.get("current_season") or "")
        if not outcome_model_version or not artifact_season:
            raise ArtifactConfigurationError("configured goal artifact has incomplete metadata")
        goal_model = load_goal_artifact(goal_path)
        goal_model.begin_season(season.label)
        home_model_uuid = goal_model.resolve_club_uuid(str(home.club_uuid), home.canonical_name)
        away_model_uuid = goal_model.resolve_club_uuid(str(away.club_uuid), away.canonical_name)
        raw_local_cutoff = goal_metadata.get("local_cutoff")
        artifact_cutoff: datetime | None = None
        if isinstance(raw_local_cutoff, dict):
            raw_observed_at = raw_local_cutoff.get("observed_at")
            if isinstance(raw_observed_at, str):
                artifact_cutoff = datetime.fromisoformat(raw_observed_at)
        raw_trained_fixtures = goal_metadata.get("trained_current_fixture_uuids")
        trained_current_fixtures = (
            {str(value) for value in raw_trained_fixtures}
            if isinstance(raw_trained_fixtures, list)
            else set()
        )

        result_home = aliased(Club)
        result_away = aliased(Club)
        prior_rows = (
            await session.execute(
                select(Match, ActualResultRevision, result_home, result_away)
                .join(
                    ActualResultRevision,
                    (ActualResultRevision.match_uuid == Match.match_uuid)
                    & ActualResultRevision.accepted.is_(True),
                )
                .join(result_home, result_home.club_uuid == Match.home_club_uuid)
                .join(result_away, result_away.club_uuid == Match.away_club_uuid)
                .where(
                    Match.season_uuid == season.season_uuid,
                    Match.current_kickoff_at < match.current_kickoff_at,
                    ActualResultRevision.observed_at < cutoff,
                    ActualResultRevision.training_eligible.is_(True),
                )
                .order_by(Match.current_kickoff_at, Match.match_uuid)
            )
        ).all()
        latest_source: datetime | None = None
        applied_results = 0
        for prior_match, actual, prior_home, prior_away in prior_rows:
            should_apply = season.label != artifact_season or (
                artifact_cutoff is not None
                and actual.observed_at > artifact_cutoff
                and str(prior_match.match_uuid) not in trained_current_fixtures
            )
            if should_apply:
                goal_model.update(
                    MatchRecord(
                        match_uuid=str(prior_match.match_uuid),
                        season=season.label,
                        kickoff_at=prior_match.current_kickoff_at,
                        available_after=actual.observed_at,
                        home_club_uuid=goal_model.resolve_club_uuid(
                            str(prior_match.home_club_uuid), prior_home.canonical_name
                        ),
                        home_club=prior_home.canonical_name,
                        away_club_uuid=goal_model.resolve_club_uuid(
                            str(prior_match.away_club_uuid), prior_away.canonical_name
                        ),
                        away_club=prior_away.canonical_name,
                        home_goals=actual.home_goals,
                        away_goals=actual.away_goals,
                        result=cast(Any, _result(actual.home_goals, actual.away_goals)),
                    )
                )
                applied_results += 1
            latest_source = (
                actual.observed_at
                if latest_source is None
                else max(latest_source, actual.observed_at)
            )
        goal_forecast = goal_model.predict(home_model_uuid, away_model_uuid)

        home_lineup, home_latest = await expected_lineup_for_club(
            session,
            match_uuid=match.match_uuid,
            season_uuid=season.season_uuid,
            club_uuid=home.club_uuid,
            club_name=home.canonical_name,
            short_name=home.short_name,
            kickoff_at=match.current_kickoff_at,
            cutoff=cutoff,
        )
        away_lineup, away_latest = await expected_lineup_for_club(
            session,
            match_uuid=match.match_uuid,
            season_uuid=season.season_uuid,
            club_uuid=away.club_uuid,
            club_name=away.canonical_name,
            short_name=away.short_name,
            kickoff_at=match.current_kickoff_at,
            cutoff=cutoff,
        )
        for observed_at in (home_latest, away_latest):
            if observed_at is not None:
                latest_source = (
                    observed_at if latest_source is None else max(latest_source, observed_at)
                )

        feature_values: dict[str, float | None] = {
            column: None for column in PREMATCH_FEATURE_COLUMNS
        }
        feature_values.update(
            {
                "goal_expected_home_goals": goal_forecast.expected_home_goals,
                "goal_expected_away_goals": goal_forecast.expected_away_goals,
                "goal_home_probability": goal_forecast.outcome_probabilities.home,
                "goal_draw_probability": goal_forecast.outcome_probabilities.draw,
                "goal_away_probability": goal_forecast.outcome_probabilities.away,
            }
        )
        statistics_predictor = load_statistics_artifact(statistics_path)
        if statistics_predictor.feature_columns != PREMATCH_FEATURE_COLUMNS:
            raise ArtifactConfigurationError("statistics artifact feature contract differs")
        matrix = np.asarray(
            [
                [
                    np.nan if feature_values[column] is None else feature_values[column]
                    for column in statistics_predictor.feature_columns
                ]
            ],
            dtype=np.float64,
        )
        statistics = statistics_predictor.predict(matrix)[0]
        raw_statistics = joblib.load(statistics_path)
        if not isinstance(raw_statistics, dict):
            raise ArtifactConfigurationError("statistics artifact metadata is invalid")
        statistics_model_version = str(raw_statistics.get("model_version") or "")
        if not statistics_model_version:
            raise ArtifactConfigurationError("statistics artifact model version is missing")

        seed_material = (
            f"{match.match_uuid}:{cutoff.isoformat()}:{outcome_model_version}:"
            f"{statistics_model_version}"
        ).encode()
        random_seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:4], "big")
        random_seed &= 0x7FFFFFFF
        return ForecastPackage(
            match_uuid=match.match_uuid,
            feature_snapshot=FeatureSnapshotInput(
                schema_version="automated-prematch-snapshot-v1",
                feature_cutoff_at=cutoff,
                latest_source_observed_at=latest_source,
                payload={
                    "season": season.label,
                    "home_club_uuid": str(home.club_uuid),
                    "away_club_uuid": str(away.club_uuid),
                    "outcome_model": {
                        "version": outcome_model_version,
                        "sha256": goal_checksum,
                        "current_season_results_applied": applied_results,
                    },
                    "statistics_model": {
                        "version": statistics_model_version,
                        "sha256": self._settings.statistics_model_sha256,
                        "missing_features_use_training_medians": True,
                    },
                    "prematch_features": feature_values,
                    "lineup_confidence": {
                        "home": home_lineup.confidence,
                        "away": away_lineup.confidence,
                    },
                },
            ),
            forecast=ModelForecast(
                outcome_model_version=outcome_model_version,
                statistics_model_version=statistics_model_version,
                expected_home_goals=goal_forecast.expected_home_goals,
                expected_away_goals=goal_forecast.expected_away_goals,
                score_matrix=goal_forecast.score_matrix,
                statistic_means=statistics.means,
                statistic_intervals_90=statistics.intervals_90,
            ),
            home_lineup=home_lineup,
            away_lineup=away_lineup,
            random_seed=random_seed,
        )
