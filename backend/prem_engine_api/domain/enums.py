"""Stable values persisted by the core domain schema."""

from enum import StrEnum


class FixtureStatus(StrEnum):
    SCHEDULED = "scheduled"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    STARTED = "started"
    SUSPENDED = "suspended"
    FINISHED = "finished"
    ABANDONED = "abandoned"
    AWARDED = "awarded"


class IdentityReviewState(StrEnum):
    RESOLVED = "resolved"
    NEEDS_REVIEW = "needs_review"


class PredictionState(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    ACTIVE_LOCKED = "active_locked"
    VOIDED = "voided"
    EVALUATED = "evaluated"
    FAILED = "failed"


class ResultKind(StrEnum):
    REGULAR = "regular"
    ABANDONED_ACCEPTED = "abandoned_accepted"
    AWARDED = "awarded"


class StandingsKind(StrEnum):
    REAL = "real"
    SIMULATED = "simulated"
    FAIR_COMPARISON = "fair_comparison"


class JobStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
