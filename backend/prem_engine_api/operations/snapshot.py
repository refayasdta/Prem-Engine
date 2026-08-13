"""Database-backed operational snapshot emitted by the minute dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.enums import (
    FixtureStatus,
    IdentityReviewState,
    JobStatus,
    KickoffPrecision,
    PredictionState,
)
from prem_engine_api.domain.models import JobRun, Match, PredictionVersion, ProviderRequestBudget
from prem_engine_api.providers.kickoffapi.client import PROVIDER


@dataclass(frozen=True)
class OperationalSnapshot:
    """Low-cardinality health values safe to include in logs and dashboards."""

    jobs_pending: int
    jobs_leased: int
    jobs_running: int
    jobs_failed: int
    t24_forecasts_missing: int
    provider_requests_today: int


async def collect_operational_snapshot(
    session: AsyncSession,
    *,
    now: datetime,
    t24_grace_seconds: int,
) -> OperationalSnapshot:
    """Count stuck work, missed T-24 forecasts, and today's provider requests."""

    active_prediction = (
        select(PredictionVersion.prediction_version_uuid)
        .where(
            PredictionVersion.match_uuid == Match.match_uuid,
            PredictionVersion.state.in_((PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)),
        )
        .exists()
    )
    missing_cutoff = now - timedelta(seconds=t24_grace_seconds)
    t24_missing = int(
        await session.scalar(
            select(func.count())
            .select_from(Match)
            .where(
                Match.status == FixtureStatus.SCHEDULED,
                Match.identity_review_state == IdentityReviewState.RESOLVED,
                Match.kickoff_precision == KickoffPrecision.EXACT,
                Match.prediction_due_at <= missing_cutoff,
                ~active_prediction,
            )
        )
        or 0
    )
    provider_requests = int(
        await session.scalar(
            select(ProviderRequestBudget.request_count).where(
                ProviderRequestBudget.provider == PROVIDER,
                ProviderRequestBudget.budget_date == now.date(),
            )
        )
        or 0
    )

    async def job_count(status: JobStatus) -> int:
        return int(
            await session.scalar(
                select(func.count()).select_from(JobRun).where(JobRun.status == status)
            )
            or 0
        )

    return OperationalSnapshot(
        jobs_pending=await job_count(JobStatus.PENDING),
        jobs_leased=await job_count(JobStatus.LEASED),
        jobs_running=await job_count(JobStatus.RUNNING),
        jobs_failed=await job_count(JobStatus.FAILED),
        t24_forecasts_missing=t24_missing,
        provider_requests_today=provider_requests,
    )
