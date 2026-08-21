"""Transactional fixture and forecast lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.enums import FixtureStatus, PredictionState
from prem_engine_api.domain.models import (
    ActualResultRevision,
    DeviceSimulation,
    FixtureScheduleRevision,
    LifecycleEvent,
    Match,
    PredictionVersion,
)


class MatchNotFoundError(LookupError):
    """Raised when a lifecycle command references an unknown canonical match."""


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")


@dataclass(frozen=True)
class RescheduleOutcome:
    """Identifiers and effects produced by a reschedule transaction."""

    revision_uuid: UUID
    prediction_voided: bool


async def _void_results_for_replay(
    session: AsyncSession,
    *,
    match_uuid: UUID,
    voided_at: datetime,
) -> int:
    """Keep old scores auditable while excluding them from rebuilt football state."""

    revisions = list(
        await session.scalars(
            select(ActualResultRevision)
            .where(
                ActualResultRevision.match_uuid == match_uuid,
                ActualResultRevision.training_eligible.is_(True),
            )
            .with_for_update()
        )
    )
    for revision in revisions:
        revision.accepted = False
        revision.training_eligible = False
        revision.voided_at = voided_at
    return len(revisions)


async def _void_device_simulations(
    session: AsyncSession,
    *,
    schedule_revision_uuid: UUID | None,
    voided_at: datetime,
    reason: str,
) -> int:
    """Retain old device timelines for replay while excluding them from current tables."""

    if schedule_revision_uuid is None:
        return 0
    simulations = list(
        await session.scalars(
            select(DeviceSimulation)
            .where(
                DeviceSimulation.schedule_revision_uuid == schedule_revision_uuid,
                DeviceSimulation.state.in_(("played", "missed")),
            )
            .with_for_update()
        )
    )
    for simulation in simulations:
        simulation.state = "void"
        simulation.voided_at = voided_at
        simulation.void_reason = reason
    return len(simulations)


async def postpone_match(
    session: AsyncSession,
    *,
    match_uuid: UUID,
    provider_status: str | None,
    actor: str,
    observed_at: datetime | None = None,
) -> bool:
    """Mark a fixture postponed and void its official prediction until a new date exists."""

    effective_observed_at = observed_at or datetime.now(UTC)
    _require_aware(effective_observed_at, "postponement observation")
    match = await session.scalar(
        select(Match).where(Match.match_uuid == match_uuid).with_for_update()
    )
    if match is None:
        raise MatchNotFoundError(str(match_uuid))
    if match.status is FixtureStatus.POSTPONED:
        return False

    voided_results = await _void_results_for_replay(
        session,
        match_uuid=match_uuid,
        voided_at=effective_observed_at,
    )

    current_revision = await session.scalar(
        select(FixtureScheduleRevision)
        .where(
            FixtureScheduleRevision.match_uuid == match_uuid,
            FixtureScheduleRevision.superseded_at.is_(None),
        )
        .with_for_update()
    )
    if current_revision is not None:
        voided_device_simulations = await _void_device_simulations(
            session,
            schedule_revision_uuid=current_revision.revision_uuid,
            voided_at=effective_observed_at,
            reason="fixture_postponed",
        )
        current_revision.superseded_at = effective_observed_at
    else:
        voided_device_simulations = 0
    revision_number = (
        await session.scalar(
            select(func.coalesce(func.max(FixtureScheduleRevision.revision_number), 0)).where(
                FixtureScheduleRevision.match_uuid == match_uuid
            )
        )
        or 0
    ) + 1
    session.add(
        FixtureScheduleRevision(
            match_uuid=match_uuid,
            revision_number=revision_number,
            kickoff_at=match.current_kickoff_at,
            canonical_status=FixtureStatus.POSTPONED,
            provider_status=provider_status,
            observed_at=effective_observed_at,
        )
    )
    active_prediction = await session.scalar(
        select(PredictionVersion)
        .where(
            PredictionVersion.match_uuid == match_uuid,
            PredictionVersion.state.in_((PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)),
        )
        .with_for_update()
    )
    prediction_voided = active_prediction is not None
    if active_prediction is not None:
        active_prediction.state = PredictionState.VOIDED
        active_prediction.voided_at = effective_observed_at
        active_prediction.void_reason = "fixture_postponed"
        session.add(
            LifecycleEvent(
                aggregate_type="prediction_version",
                aggregate_uuid=active_prediction.prediction_version_uuid,
                event_type="prediction_voided",
                actor=actor,
                payload={"reason": "fixture_postponed", "match_uuid": str(match_uuid)},
            )
        )
    match.status = FixtureStatus.POSTPONED
    session.add(
        LifecycleEvent(
            aggregate_type="match",
            aggregate_uuid=match_uuid,
            event_type="fixture_postponed",
            actor=actor,
            payload={
                "prediction_voided": prediction_voided,
                "result_revisions_voided": voided_results,
                "device_simulations_voided": voided_device_simulations,
            },
        )
    )
    await session.flush()
    return prediction_voided


async def cancel_match(
    session: AsyncSession,
    *,
    match_uuid: UUID,
    provider_status: str | None,
    actor: str,
    observed_at: datetime | None = None,
) -> bool:
    """Cancel a fixture, void its prediction, and do not schedule a replacement."""

    effective_observed_at = observed_at or datetime.now(UTC)
    _require_aware(effective_observed_at, "cancellation observation")
    match = await session.scalar(
        select(Match).where(Match.match_uuid == match_uuid).with_for_update()
    )
    if match is None:
        raise MatchNotFoundError(str(match_uuid))
    if match.status is FixtureStatus.CANCELLED:
        return False

    voided_results = await _void_results_for_replay(
        session,
        match_uuid=match_uuid,
        voided_at=effective_observed_at,
    )

    current_revision = await session.scalar(
        select(FixtureScheduleRevision)
        .where(
            FixtureScheduleRevision.match_uuid == match_uuid,
            FixtureScheduleRevision.superseded_at.is_(None),
        )
        .with_for_update()
    )
    if current_revision is not None:
        voided_device_simulations = await _void_device_simulations(
            session,
            schedule_revision_uuid=current_revision.revision_uuid,
            voided_at=effective_observed_at,
            reason="fixture_cancelled",
        )
        current_revision.superseded_at = effective_observed_at
    else:
        voided_device_simulations = 0
    revision_number = (
        await session.scalar(
            select(func.coalesce(func.max(FixtureScheduleRevision.revision_number), 0)).where(
                FixtureScheduleRevision.match_uuid == match_uuid
            )
        )
        or 0
    ) + 1
    session.add(
        FixtureScheduleRevision(
            match_uuid=match_uuid,
            revision_number=revision_number,
            kickoff_at=match.current_kickoff_at,
            canonical_status=FixtureStatus.CANCELLED,
            provider_status=provider_status,
            observed_at=effective_observed_at,
        )
    )
    active_prediction = await session.scalar(
        select(PredictionVersion)
        .where(
            PredictionVersion.match_uuid == match_uuid,
            PredictionVersion.state.in_((PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)),
        )
        .with_for_update()
    )
    prediction_voided = active_prediction is not None
    if active_prediction is not None:
        active_prediction.state = PredictionState.VOIDED
        active_prediction.voided_at = effective_observed_at
        active_prediction.void_reason = "fixture_cancelled"
        session.add(
            LifecycleEvent(
                aggregate_type="prediction_version",
                aggregate_uuid=active_prediction.prediction_version_uuid,
                event_type="prediction_voided",
                actor=actor,
                payload={"reason": "fixture_cancelled", "match_uuid": str(match_uuid)},
            )
        )
    match.status = FixtureStatus.CANCELLED
    session.add(
        LifecycleEvent(
            aggregate_type="match",
            aggregate_uuid=match_uuid,
            event_type="fixture_cancelled",
            actor=actor,
            payload={
                "prediction_voided": prediction_voided,
                "result_revisions_voided": voided_results,
                "device_simulations_voided": voided_device_simulations,
            },
        )
    )
    await session.flush()
    return prediction_voided


async def reschedule_match(
    session: AsyncSession,
    *,
    match_uuid: UUID,
    revised_kickoff_at: datetime,
    provider_status: str | None,
    actor: str,
    observed_at: datetime | None = None,
) -> RescheduleOutcome:
    """Replace the current schedule and void any official active forecast atomically."""

    effective_observed_at = observed_at or datetime.now(UTC)
    _require_aware(effective_observed_at, "reschedule observation")
    _require_aware(revised_kickoff_at, "revised kickoff")
    match = await session.scalar(
        select(Match).where(Match.match_uuid == match_uuid).with_for_update()
    )
    if match is None:
        raise MatchNotFoundError(str(match_uuid))

    voided_results = await _void_results_for_replay(
        session,
        match_uuid=match_uuid,
        voided_at=effective_observed_at,
    )

    current_revision = await session.scalar(
        select(FixtureScheduleRevision)
        .where(
            FixtureScheduleRevision.match_uuid == match_uuid,
            FixtureScheduleRevision.superseded_at.is_(None),
        )
        .with_for_update()
    )
    if current_revision is not None:
        voided_device_simulations = await _void_device_simulations(
            session,
            schedule_revision_uuid=current_revision.revision_uuid,
            voided_at=effective_observed_at,
            reason="fixture_rescheduled",
        )
        current_revision.superseded_at = effective_observed_at
    else:
        voided_device_simulations = 0

    revision_number = (
        await session.scalar(
            select(func.coalesce(func.max(FixtureScheduleRevision.revision_number), 0)).where(
                FixtureScheduleRevision.match_uuid == match_uuid
            )
        )
        or 0
    ) + 1
    revision = FixtureScheduleRevision(
        match_uuid=match_uuid,
        revision_number=revision_number,
        kickoff_at=revised_kickoff_at,
        canonical_status=FixtureStatus.SCHEDULED,
        provider_status=provider_status,
        observed_at=effective_observed_at,
    )
    session.add(revision)

    active_prediction = await session.scalar(
        select(PredictionVersion)
        .where(
            PredictionVersion.match_uuid == match_uuid,
            PredictionVersion.state.in_((PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)),
        )
        .with_for_update()
    )
    prediction_voided = active_prediction is not None
    if active_prediction is not None:
        active_prediction.state = PredictionState.VOIDED
        active_prediction.voided_at = effective_observed_at
        active_prediction.void_reason = "fixture_postponed"
        session.add(
            LifecycleEvent(
                aggregate_type="prediction_version",
                aggregate_uuid=active_prediction.prediction_version_uuid,
                event_type="prediction_voided",
                actor=actor,
                payload={"reason": "fixture_postponed", "match_uuid": str(match_uuid)},
            )
        )

    match.status = FixtureStatus.SCHEDULED
    match.current_kickoff_at = revised_kickoff_at
    match.prediction_due_at = revised_kickoff_at - timedelta(hours=24)

    session.add(
        LifecycleEvent(
            aggregate_type="match",
            aggregate_uuid=match_uuid,
            event_type="fixture_rescheduled",
            actor=actor,
            payload={
                "revision_number": revision_number,
                "revised_kickoff_at": revised_kickoff_at.isoformat(),
                "prediction_voided": prediction_voided,
                "result_revisions_voided": voided_results,
                "device_simulations_voided": voided_device_simulations,
            },
        )
    )
    await session.flush()
    return RescheduleOutcome(
        revision_uuid=revision.revision_uuid,
        prediction_voided=prediction_voided,
    )
