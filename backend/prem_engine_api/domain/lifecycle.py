"""Transactional fixture and forecast lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.enums import FixtureStatus, JobStatus, PredictionState
from prem_engine_api.domain.models import (
    FixtureScheduleRevision,
    JobRun,
    LifecycleEvent,
    Match,
    PredictionVersion,
)


class MatchNotFoundError(LookupError):
    """Raised when a lifecycle command references an unknown canonical match."""


@dataclass(frozen=True)
class RescheduleOutcome:
    """Identifiers and effects produced by a reschedule transaction."""

    revision_uuid: UUID
    prediction_voided: bool
    replacement_job_uuid: UUID


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
    match = await session.scalar(
        select(Match).where(Match.match_uuid == match_uuid).with_for_update()
    )
    if match is None:
        raise MatchNotFoundError(str(match_uuid))

    current_revision = await session.scalar(
        select(FixtureScheduleRevision)
        .where(
            FixtureScheduleRevision.match_uuid == match_uuid,
            FixtureScheduleRevision.superseded_at.is_(None),
        )
        .with_for_update()
    )
    if current_revision is not None:
        current_revision.superseded_at = effective_observed_at

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

    replacement_job_uuid = uuid4()
    session.add(
        JobRun(
            job_uuid=replacement_job_uuid,
            idempotency_key=f"generate_prediction:{match_uuid}:{revision_number}",
            job_type="generate_prediction",
            status=JobStatus.PENDING,
            match_uuid=match_uuid,
            due_at=match.prediction_due_at,
            attempt_count=0,
        )
    )
    if prediction_voided:
        session.add(
            JobRun(
                idempotency_key=f"recalculate_simulated_standings:{match_uuid}:{revision_number}",
                job_type="recalculate_simulated_standings",
                status=JobStatus.PENDING,
                match_uuid=match_uuid,
                due_at=effective_observed_at,
                attempt_count=0,
            )
        )
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
            },
        )
    )
    await session.flush()
    return RescheduleOutcome(
        revision_uuid=revision.revision_uuid,
        prediction_voided=prediction_voided,
        replacement_job_uuid=replacement_job_uuid,
    )
