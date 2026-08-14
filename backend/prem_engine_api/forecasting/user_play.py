"""Atomic, per-device user-triggered simulation lifecycle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from prem_engine_modeling.simulation import (
    SimulationForecast,
    SimulationLineup,
    SimulationPlayer,
    generate_stored_simulation,
    validate_simulation_consistency,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import FixtureStatus, IdentityReviewState, KickoffPrecision
from prem_engine_api.domain.models import (
    DeviceSimulation,
    FixtureScheduleRevision,
    LocalModelArtifact,
    LocalWorkerState,
    Match,
)
from prem_engine_api.forecasting.contracts import ForecastPackage, LineupPlayer, TeamLineup
from prem_engine_api.forecasting.inference import OfficialArtifactForecastFactory

PLAY_WINDOW_BEFORE = timedelta(hours=24)
PLAY_WINDOW_AFTER = timedelta(minutes=45)


class PlayForecastFactory(Protocol):
    async def build(
        self, session: AsyncSession, *, match_uuid: UUID, cutoff: datetime
    ) -> ForecastPackage: ...


class UserPlayError(RuntimeError):
    """A stable user-facing rejection from the server-side Play policy."""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class PlayContext:
    match: Match
    revision: FixtureScheduleRevision | None
    simulation: DeviceSimulation | None
    data_current: bool


@dataclass(frozen=True)
class PlayOutcome:
    simulation: DeviceSimulation
    created: bool


def _json_checksum(payload: Any) -> str:
    body = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
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


def play_window(revision: FixtureScheduleRevision) -> tuple[datetime, datetime]:
    return revision.kickoff_at - PLAY_WINDOW_BEFORE, revision.kickoff_at + PLAY_WINDOW_AFTER


async def fixture_data_is_current(
    session: AsyncSession, *, settings: Settings, now: datetime
) -> bool:
    worker = await session.scalar(
        select(LocalWorkerState).where(LocalWorkerState.singleton_key == 1)
    )
    return bool(
        worker is not None
        and worker.last_fixture_success_at is not None
        and (now - worker.last_fixture_success_at).total_seconds()
        <= settings.local_fixture_freshness_seconds
    )


async def load_play_context(
    session: AsyncSession,
    *,
    match_uuid: UUID,
    device_uuid: UUID,
    settings: Settings,
    now: datetime,
    record_missed: bool = True,
) -> PlayContext | None:
    """Load current device state and permanently record a closed, unplayed window."""

    match = await session.scalar(
        select(Match)
        .where(Match.match_uuid == match_uuid)
        .with_for_update(of=Match if record_missed else None)
    )
    if match is None:
        return None
    revision = await session.scalar(
        select(FixtureScheduleRevision).where(
            FixtureScheduleRevision.match_uuid == match_uuid,
            FixtureScheduleRevision.superseded_at.is_(None),
        )
    )
    simulation: DeviceSimulation | None = None
    if revision is not None:
        simulation = await session.scalar(
            select(DeviceSimulation).where(
                DeviceSimulation.device_uuid == device_uuid,
                DeviceSimulation.match_uuid == match_uuid,
                DeviceSimulation.schedule_revision_uuid == revision.revision_uuid,
            )
        )
        if simulation is None and record_missed:
            _, closes_at = play_window(revision)
            if (
                now > closes_at
                and revision.canonical_status
                not in (FixtureStatus.POSTPONED, FixtureStatus.CANCELLED)
            ):
                simulation = DeviceSimulation(
                    device_uuid=device_uuid,
                    match_uuid=match_uuid,
                    schedule_revision_uuid=revision.revision_uuid,
                    schedule_revision_number=revision.revision_number,
                    state="missed",
                    missed_at=now,
                )
                session.add(simulation)
                await session.flush()
    return PlayContext(
        match=match,
        revision=revision,
        simulation=simulation,
        data_current=await fixture_data_is_current(session, settings=settings, now=now),
    )


def _raise_if_ineligible(context: PlayContext, *, now: datetime) -> None:
    match = context.match
    revision = context.revision
    if revision is None:
        raise UserPlayError(
            "schedule_revision_missing",
            "The current fixture schedule has not been synchronized yet.",
            status_code=409,
        )
    if revision.canonical_status is FixtureStatus.POSTPONED:
        raise UserPlayError(
            "fixture_postponed",
            "Play is unavailable while this fixture is postponed.",
            status_code=409,
        )
    if revision.canonical_status is FixtureStatus.CANCELLED:
        raise UserPlayError(
            "fixture_cancelled", "This fixture was cancelled.", status_code=409
        )
    if (
        match.identity_review_state is not IdentityReviewState.RESOLVED
        or match.kickoff_precision is not KickoffPrecision.EXACT
    ):
        raise UserPlayError(
            "fixture_unresolved",
            "The canonical fixture identity or kickoff time is not exact.",
            status_code=409,
        )
    opens_at, closes_at = play_window(revision)
    if now < opens_at:
        raise UserPlayError(
            "play_window_locked",
            "Play unlocks exactly 24 hours before kickoff.",
            status_code=423,
        )
    if now > closes_at:
        raise UserPlayError(
            "play_window_missed",
            "The Play window closed 45 minutes after kickoff.",
            status_code=410,
        )
    if not context.data_current:
        raise UserPlayError(
            "fixture_data_stale",
            "Fixture data is stale. Play will unlock after synchronization succeeds.",
            status_code=503,
        )


async def play_device_simulation(
    session: AsyncSession,
    *,
    match_uuid: UUID,
    device_uuid: UUID,
    settings: Settings,
    now: datetime,
    forecast_factory: PlayForecastFactory | None = None,
) -> PlayOutcome:
    """Generate exactly one device simulation inside the inclusive Play window."""

    context = await load_play_context(
        session,
        match_uuid=match_uuid,
        device_uuid=device_uuid,
        settings=settings,
        now=now,
        record_missed=True,
    )
    if context is None:
        raise UserPlayError("match_not_found", "Match not found.", status_code=404)
    if context.simulation is not None:
        if context.simulation.state == "played":
            return PlayOutcome(simulation=context.simulation, created=False)
        if context.simulation.state == "missed":
            raise UserPlayError(
                "play_window_missed",
                "The Play window closed 45 minutes after kickoff.",
                status_code=410,
            )
        raise UserPlayError(
            "schedule_revision_void",
            "That schedule revision is void and cannot be played again.",
            status_code=409,
        )
    _raise_if_ineligible(context, now=now)
    revision = context.revision
    assert revision is not None

    factory = forecast_factory or OfficialArtifactForecastFactory(settings)
    cutoff = revision.kickoff_at - PLAY_WINDOW_BEFORE
    package = await factory.build(session, match_uuid=match_uuid, cutoff=cutoff)
    outcome = package.forecast
    seed_material = (
        f"{device_uuid}:{match_uuid}:{revision.revision_uuid}:"
        f"{outcome.outcome_model_version}"
    ).encode()
    random_seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:4], "big")
    random_seed &= 0x7FFFFFFF
    record_token = uuid4()
    simulation_payload = generate_stored_simulation(
        SimulationForecast(
            match_uuid=str(match_uuid),
            prediction_version_uuid=str(record_token),
            feature_cutoff_at=cutoff.isoformat(),
            locked_at=now.isoformat(),
            outcome_model_version=outcome.outcome_model_version,
            statistics_model_version=outcome.statistics_model_version,
            expected_home_goals=outcome.expected_home_goals,
            expected_away_goals=outcome.expected_away_goals,
            score_matrix=outcome.score_matrix,
            statistic_means=outcome.statistic_means,
            home_lineup=_simulation_lineup(package.home_lineup),
            away_lineup=_simulation_lineup(package.away_lineup),
        ),
        random_seed=random_seed,
    )
    validate_simulation_consistency(simulation_payload)
    home_probability = sum(
        probability
        for home_goals, row in enumerate(outcome.score_matrix)
        for away_goals, probability in enumerate(row)
        if home_goals > away_goals
    )
    draw_probability = sum(
        row[index] for index, row in enumerate(outcome.score_matrix) if index < len(row)
    )
    away_probability = max(0.0, 1.0 - home_probability - draw_probability)
    feature_payload = {
        "schema_version": package.feature_snapshot.schema_version,
        "feature_cutoff_at": cutoff.isoformat(),
        "latest_source_observed_at": (
            package.feature_snapshot.latest_source_observed_at.isoformat()
            if package.feature_snapshot.latest_source_observed_at is not None
            else None
        ),
        "features": package.feature_snapshot.payload,
    }
    lineups = {
        "schema_version": "predicted-lineups-v1",
        "home": _lineup_payload(package.home_lineup),
        "away": _lineup_payload(package.away_lineup),
    }
    outcome_source = package.feature_snapshot.payload.get("outcome_model")
    model_checksum = (
        str(outcome_source.get("sha256"))
        if isinstance(outcome_source, dict) and outcome_source.get("sha256")
        else None
    )
    artifact = await session.scalar(
        select(LocalModelArtifact)
        .where(
            LocalModelArtifact.model_version == outcome.outcome_model_version,
            LocalModelArtifact.status == "succeeded",
        )
        .limit(1)
    )
    simulation = DeviceSimulation(
        device_simulation_uuid=UUID(simulation_payload.simulation_uuid),
        device_uuid=device_uuid,
        match_uuid=match_uuid,
        schedule_revision_uuid=revision.revision_uuid,
        schedule_revision_number=revision.revision_number,
        state="played",
        play_classification=(
            "pre_kickoff_user_simulation"
            if now < revision.kickoff_at
            else "in_play_user_simulation"
        ),
        generated_at=now,
        feature_cutoff_at=cutoff,
        latest_source_observed_at=package.feature_snapshot.latest_source_observed_at,
        feature_snapshot=feature_payload,
        feature_snapshot_checksum=_json_checksum(feature_payload),
        model_version=outcome.outcome_model_version,
        statistics_model_version=outcome.statistics_model_version,
        model_artifact_uuid=artifact.artifact_uuid if artifact is not None else None,
        model_artifact_checksum=model_checksum,
        expected_home_goals=_decimal(outcome.expected_home_goals, "0.0001"),
        expected_away_goals=_decimal(outcome.expected_away_goals, "0.0001"),
        home_win_probability=_decimal(home_probability, "0.00000001"),
        draw_probability=_decimal(draw_probability, "0.00000001"),
        away_win_probability=_decimal(away_probability, "0.00000001"),
        statistics_distribution={
            "schema_version": "forecast-statistics-v1",
            "statistics_model_version": outcome.statistics_model_version,
            "score_matrix": [list(row) for row in outcome.score_matrix],
            "means": outcome.statistic_means,
            "intervals_90": {
                key: list(value) for key, value in outcome.statistic_intervals_90.items()
            },
        },
        expected_lineups=lineups,
        random_seed=random_seed,
        home_goals=simulation_payload.home_goals,
        away_goals=simulation_payload.away_goals,
        statistics=simulation_payload.statistics,
        events=[asdict(event) for event in simulation_payload.events],
        simulation_checksum=simulation_payload.checksum,
        presentation_started_at=now,
        presentation_duration_seconds=settings.simulation_presentation_seconds,
    )
    session.add(simulation)
    await session.flush()
    return PlayOutcome(simulation=simulation, created=True)
