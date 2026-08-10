"""PostgreSQL-backed idempotent job scheduling and leases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.enums import (
    FixtureStatus,
    IdentityReviewState,
    JobStatus,
    KickoffPrecision,
)
from prem_engine_api.domain.models import FixtureScheduleRevision, JobRun, Match

GENERATE_PREDICTION_JOB = "generate_prediction"


class JobLeaseError(RuntimeError):
    """Raised when a worker attempts an invalid lease transition."""


@dataclass(frozen=True)
class ClaimedJob:
    job_uuid: UUID
    match_uuid: UUID | None
    job_type: str
    attempt_count: int
    lease_owner: str


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")


async def enqueue_prediction_jobs(session: AsyncSession, *, now: datetime) -> int:
    """Create each current schedule revision's generation job exactly once."""

    _aware(now, "scheduler time")
    revisions = (
        await session.execute(
            select(Match, FixtureScheduleRevision.revision_number)
            .join(
                FixtureScheduleRevision,
                and_(
                    FixtureScheduleRevision.match_uuid == Match.match_uuid,
                    FixtureScheduleRevision.superseded_at.is_(None),
                ),
            )
            .where(
                Match.status == FixtureStatus.SCHEDULED,
                Match.identity_review_state == IdentityReviewState.RESOLVED,
                Match.kickoff_precision == KickoffPrecision.EXACT,
            )
        )
    ).all()
    created = 0
    for match, revision_number in revisions:
        statement = (
            insert(JobRun)
            .values(
                idempotency_key=(f"{GENERATE_PREDICTION_JOB}:{match.match_uuid}:{revision_number}"),
                job_type=GENERATE_PREDICTION_JOB,
                status=JobStatus.PENDING,
                match_uuid=match.match_uuid,
                due_at=match.prediction_due_at,
                attempt_count=0,
            )
            .on_conflict_do_nothing(index_elements=[JobRun.idempotency_key])
            .returning(JobRun.job_uuid)
        )
        created += int((await session.scalar(statement)) is not None)
    await session.flush()
    return created


async def claim_due_jobs(
    session: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    lease_duration: timedelta,
    limit: int,
    max_attempts: int,
    job_types: tuple[str, ...] | None = None,
) -> tuple[ClaimedJob, ...]:
    """Lease due work without allowing two dispatchers to claim the same row."""

    _aware(now, "claim time")
    if not worker_id.strip():
        raise ValueError("worker ID is required")
    if lease_duration <= timedelta(0) or limit <= 0 or max_attempts <= 0:
        raise ValueError("lease duration, limit, and maximum attempts must be positive")
    filters = [
        JobRun.due_at <= now,
        JobRun.attempt_count < max_attempts,
        or_(
            JobRun.status == JobStatus.PENDING,
            and_(
                JobRun.status.in_((JobStatus.LEASED, JobStatus.RUNNING)),
                JobRun.lease_expires_at < now,
            ),
        ),
    ]
    if job_types is not None:
        if not job_types:
            raise ValueError("job type filter cannot be empty")
        filters.append(JobRun.job_type.in_(job_types))
    jobs = list(
        await session.scalars(
            select(JobRun)
            .where(*filters)
            .order_by(JobRun.due_at, JobRun.created_at, JobRun.job_uuid)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    claimed: list[ClaimedJob] = []
    for job in jobs:
        job.status = JobStatus.LEASED
        job.lease_owner = worker_id
        job.lease_expires_at = now + lease_duration
        job.attempt_count += 1
        job.last_error_code = None
        job.finished_at = None
        claimed.append(
            ClaimedJob(
                job_uuid=job.job_uuid,
                match_uuid=job.match_uuid,
                job_type=job.job_type,
                attempt_count=job.attempt_count,
                lease_owner=worker_id,
            )
        )
    await session.flush()
    return tuple(claimed)


async def start_job(
    session: AsyncSession, *, job_uuid: UUID, worker_id: str, now: datetime
) -> JobRun:
    _aware(now, "job start time")
    job = await session.scalar(select(JobRun).where(JobRun.job_uuid == job_uuid).with_for_update())
    if job is None or job.status is not JobStatus.LEASED or job.lease_owner != worker_id:
        raise JobLeaseError("job is not leased by this worker")
    if job.lease_expires_at is None or job.lease_expires_at <= now:
        raise JobLeaseError("job lease has expired")
    job.status = JobStatus.RUNNING
    job.started_at = now
    await session.flush()
    return job


async def fail_job(
    session: AsyncSession,
    *,
    job_uuid: UUID,
    worker_id: str,
    now: datetime,
    error_code: str,
    max_attempts: int,
    retry_delay: timedelta,
) -> JobStatus:
    """Record only a safe error code and either retry or terminally fail."""

    _aware(now, "job failure time")
    if not error_code or len(error_code) > 120:
        raise ValueError("a short error code is required")
    job = await session.scalar(select(JobRun).where(JobRun.job_uuid == job_uuid).with_for_update())
    if job is None or job.lease_owner != worker_id:
        raise JobLeaseError("job is not owned by this worker")
    job.last_error_code = error_code
    job.lease_owner = None
    job.lease_expires_at = None
    if job.attempt_count >= max_attempts:
        job.status = JobStatus.FAILED
        job.finished_at = now
    else:
        job.status = JobStatus.PENDING
        job.due_at = now + retry_delay
        job.finished_at = None
    await session.flush()
    return job.status
