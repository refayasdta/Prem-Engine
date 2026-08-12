"""Atomic persistence of one official forecast and its stored simulation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from prem_engine_modeling.simulation import (
    SimulationForecast,
    SimulationLineup,
    SimulationPlayer,
    generate_stored_simulation,
    validate_simulation_consistency,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.enums import (
    FixtureStatus,
    IdentityReviewState,
    JobStatus,
    KickoffPrecision,
    PredictionState,
)
from prem_engine_api.domain.models import (
    FeatureSnapshot,
    JobRun,
    LifecycleEvent,
    Match,
    PredictedLineup,
    PredictionVersion,
    StoredSimulation,
)
from prem_engine_api.forecasting.contracts import ForecastPackage, LineupPlayer, TeamLineup
from prem_engine_api.jobs.leases import GENERATE_PREDICTION_JOB, JobLeaseError


class ForecastGenerationError(RuntimeError):
    """Raised before persistence when an official forecast cannot be locked safely."""


@dataclass(frozen=True)
class LockedForecast:
    prediction_version_uuid: UUID
    simulation_uuid: UUID
    created: bool


def _json_checksum(payload: Any) -> str:
    body = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _decimal(value: float, places: str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places))


def _player_payload(player: LineupPlayer) -> dict[str, Any]:
    return {
        "player_uuid": str(player.player_uuid),
        "name": player.name,
        "position": player.position,
        "shirt_number": player.shirt_number,
        "shirt_number_source": player.shirt_number_source,
        "starting_probability": player.starting_probability,
        "availability_probability": player.availability_probability,
    }


def _lineup_payload(lineup: TeamLineup) -> dict[str, Any]:
    return {
        "club_uuid": str(lineup.club_uuid),
        "club_name": lineup.club_name,
        "short_name": lineup.short_name,
        "formation": lineup.formation,
        "confidence": lineup.confidence,
        "starters": [_player_payload(player) for player in lineup.starters],
        "substitutes": [_player_payload(player) for player in lineup.substitutes],
    }


def _simulation_lineup(lineup: TeamLineup) -> SimulationLineup:
    def convert(player: LineupPlayer) -> SimulationPlayer:
        return SimulationPlayer(
            player_uuid=str(player.player_uuid),
            name=player.name,
            position=player.position,
            shirt_number=player.shirt_number,
        )

    return SimulationLineup(
        club_uuid=str(lineup.club_uuid),
        club_name=lineup.club_name,
        short_name=lineup.short_name,
        formation=lineup.formation,
        starters=tuple(convert(player) for player in lineup.starters),
        substitutes=tuple(convert(player) for player in lineup.substitutes),
    )


async def lock_forecast(
    session: AsyncSession,
    *,
    job_uuid: UUID,
    worker_id: str,
    package: ForecastPackage,
    locked_at: datetime,
    presentation_duration_seconds: int = 60,
    actor: str = "forecast-worker",
) -> LockedForecast:
    """Write snapshot, lineup, forecast, and simulation in one transaction."""

    if locked_at.tzinfo is None or locked_at.utcoffset() is None:
        raise ValueError("forecast lock time must include a timezone")
    if presentation_duration_seconds <= 0:
        raise ValueError("presentation duration must be positive")
    match = await session.scalar(
        select(Match).where(Match.match_uuid == package.match_uuid).with_for_update()
    )
    if match is None:
        raise ForecastGenerationError("canonical match does not exist")
    job = await session.scalar(select(JobRun).where(JobRun.job_uuid == job_uuid).with_for_update())
    if (
        job is None
        or job.job_type != GENERATE_PREDICTION_JOB
        or job.status is not JobStatus.RUNNING
        or job.lease_owner != worker_id
        or job.match_uuid != package.match_uuid
    ):
        raise JobLeaseError("running generation job is not owned by this worker")
    if job.lease_expires_at is None or job.lease_expires_at <= locked_at:
        raise JobLeaseError("generation job lease expired before the forecast was locked")

    if (
        match.status is not FixtureStatus.SCHEDULED
        or match.identity_review_state is not IdentityReviewState.RESOLVED
        or match.kickoff_precision is not KickoffPrecision.EXACT
    ):
        raise ForecastGenerationError("match is not eligible for an official forecast")
    if package.feature_snapshot.feature_cutoff_at != match.prediction_due_at:
        raise ForecastGenerationError("feature cutoff does not match the current schedule")
    if package.home_lineup.club_uuid != match.home_club_uuid:
        raise ForecastGenerationError("home expected lineup belongs to the wrong club")
    if package.away_lineup.club_uuid != match.away_club_uuid:
        raise ForecastGenerationError("away expected lineup belongs to the wrong club")

    existing = await session.scalar(
        select(PredictionVersion).where(
            PredictionVersion.match_uuid == match.match_uuid,
            PredictionVersion.state.in_((PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)),
        )
    )
    if existing is not None:
        existing_simulation = await session.scalar(
            select(StoredSimulation).where(
                StoredSimulation.prediction_version_uuid == existing.prediction_version_uuid
            )
        )
        if existing_simulation is None:
            raise ForecastGenerationError("active prediction has no stored simulation")
        job.status = JobStatus.SUCCEEDED
        job.finished_at = locked_at
        job.lease_owner = None
        job.lease_expires_at = None
        await session.flush()
        return LockedForecast(
            prediction_version_uuid=existing.prediction_version_uuid,
            simulation_uuid=existing_simulation.simulation_uuid,
            created=False,
        )

    version_number = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(PredictionVersion.version_number), 0)).where(
                    PredictionVersion.match_uuid == match.match_uuid
                )
            )
            or 0
        )
        + 1
    )
    prediction_uuid = uuid4()
    feature_payload = {
        "schema_version": package.feature_snapshot.schema_version,
        "feature_cutoff_at": package.feature_snapshot.feature_cutoff_at.isoformat(),
        "latest_source_observed_at": (
            package.feature_snapshot.latest_source_observed_at.isoformat()
            if package.feature_snapshot.latest_source_observed_at is not None
            else None
        ),
        "features": package.feature_snapshot.payload,
    }
    feature_checksum = _json_checksum(feature_payload)
    outcome = package.forecast
    probabilities = (
        sum(
            probability
            for home_goals, row in enumerate(outcome.score_matrix)
            for away_goals, probability in enumerate(row)
            if home_goals > away_goals
        ),
        sum(row[index] for index, row in enumerate(outcome.score_matrix)),
    )
    home_probability, draw_probability = probabilities
    away_probability = max(0.0, 1.0 - home_probability - draw_probability)
    statistics_distribution = {
        "schema_version": "forecast-statistics-v1",
        "statistics_model_version": outcome.statistics_model_version,
        "score_matrix": [list(row) for row in outcome.score_matrix],
        "means": outcome.statistic_means,
        "intervals_90": {key: list(value) for key, value in outcome.statistic_intervals_90.items()},
    }
    prediction = PredictionVersion(
        prediction_version_uuid=prediction_uuid,
        match_uuid=match.match_uuid,
        version_number=version_number,
        state=PredictionState.GENERATING,
        feature_cutoff_at=package.feature_snapshot.feature_cutoff_at,
        model_version=outcome.outcome_model_version,
        feature_snapshot_checksum=feature_checksum,
        home_win_probability=_decimal(home_probability, "0.00000001"),
        draw_probability=_decimal(draw_probability, "0.00000001"),
        away_win_probability=_decimal(away_probability, "0.00000001"),
        expected_home_goals=_decimal(outcome.expected_home_goals, "0.0001"),
        expected_away_goals=_decimal(outcome.expected_away_goals, "0.0001"),
        statistics_distribution=statistics_distribution,
    )
    session.add(prediction)
    await session.flush()

    home_lineup_payload = _lineup_payload(package.home_lineup)
    away_lineup_payload = _lineup_payload(package.away_lineup)
    combined_lineup_payload = {
        "schema_version": "predicted-lineups-v1",
        "home": home_lineup_payload,
        "away": away_lineup_payload,
    }
    session.add_all(
        (
            FeatureSnapshot(
                prediction_version_uuid=prediction_uuid,
                schema_version=package.feature_snapshot.schema_version,
                feature_cutoff_at=package.feature_snapshot.feature_cutoff_at,
                latest_source_observed_at=(package.feature_snapshot.latest_source_observed_at),
                feature_payload=package.feature_snapshot.payload,
                checksum=feature_checksum,
            ),
            PredictedLineup(
                prediction_version_uuid=prediction_uuid,
                formation="dual",
                lineup_payload=combined_lineup_payload,
                checksum=_json_checksum(combined_lineup_payload),
            ),
        )
    )
    simulation_payload = generate_stored_simulation(
        SimulationForecast(
            match_uuid=str(match.match_uuid),
            prediction_version_uuid=str(prediction_uuid),
            feature_cutoff_at=package.feature_snapshot.feature_cutoff_at.isoformat(),
            locked_at=locked_at.isoformat(),
            outcome_model_version=outcome.outcome_model_version,
            statistics_model_version=outcome.statistics_model_version,
            expected_home_goals=outcome.expected_home_goals,
            expected_away_goals=outcome.expected_away_goals,
            score_matrix=outcome.score_matrix,
            statistic_means=outcome.statistic_means,
            home_lineup=_simulation_lineup(package.home_lineup),
            away_lineup=_simulation_lineup(package.away_lineup),
        ),
        random_seed=package.random_seed,
    )
    validate_simulation_consistency(simulation_payload)
    stored = StoredSimulation(
        simulation_uuid=UUID(simulation_payload.simulation_uuid),
        prediction_version_uuid=prediction_uuid,
        random_seed=simulation_payload.random_seed,
        home_goals=simulation_payload.home_goals,
        away_goals=simulation_payload.away_goals,
        statistics=simulation_payload.statistics,
        events=[asdict(event) for event in simulation_payload.events],
        checksum=simulation_payload.checksum,
        presentation_started_at=locked_at,
        presentation_duration_seconds=presentation_duration_seconds,
    )
    session.add(stored)
    await session.flush()

    prediction.state = PredictionState.ACTIVE_LOCKED
    prediction.locked_at = locked_at
    job.status = JobStatus.SUCCEEDED
    job.finished_at = locked_at
    job.lease_owner = None
    job.lease_expires_at = None
    session.add_all(
        (
            LifecycleEvent(
                aggregate_type="prediction_version",
                aggregate_uuid=prediction_uuid,
                event_type="prediction_locked",
                actor=actor,
                payload={
                    "match_uuid": str(match.match_uuid),
                    "version_number": version_number,
                    "feature_snapshot_checksum": feature_checksum,
                    "simulation_checksum": simulation_payload.checksum,
                },
            ),
            JobRun(
                idempotency_key=f"recalculate_simulated_standings:{prediction_uuid}",
                job_type="recalculate_simulated_standings",
                status=JobStatus.PENDING,
                match_uuid=match.match_uuid,
                due_at=locked_at + timedelta(seconds=presentation_duration_seconds),
                attempt_count=0,
            ),
        )
    )
    await session.flush()
    return LockedForecast(
        prediction_version_uuid=prediction_uuid,
        simulation_uuid=stored.simulation_uuid,
        created=True,
    )
