"""Shared synchronized clock for the fixed one-minute stored replay."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

PresentationPhase = Literal["countdown", "first_half", "half_time", "second_half", "complete"]


@dataclass(frozen=True)
class PresentationClock:
    phase: PresentationPhase
    elapsed_seconds: float
    remaining_seconds: int
    football_second: int
    complete: bool


def presentation_clock(
    *, started_at: datetime, duration_seconds: int, now: datetime
) -> PresentationClock:
    """Map wall time to 25s first half, 10s interval, and 25s second half."""

    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("presentation start must include a timezone")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("presentation time must include a timezone")
    if duration_seconds <= 0:
        raise ValueError("presentation duration must be positive")
    raw_elapsed = (now - started_at).total_seconds()
    if raw_elapsed < 0:
        return PresentationClock(
            phase="countdown",
            elapsed_seconds=0.0,
            remaining_seconds=math.ceil(-raw_elapsed),
            football_second=0,
            complete=False,
        )
    elapsed = min(float(duration_seconds), raw_elapsed)
    scale = duration_seconds / 60
    first_half_end = 25 * scale
    interval_end = 35 * scale
    if elapsed < first_half_end:
        football_second = int(2700 * elapsed / first_half_end)
        phase: PresentationPhase = "first_half"
    elif elapsed < interval_end:
        football_second = 2700
        phase = "half_time"
    elif elapsed < duration_seconds:
        football_second = 2700 + int(
            2700 * (elapsed - interval_end) / (duration_seconds - interval_end)
        )
        phase = "second_half"
    else:
        football_second = 5400
        phase = "complete"
    return PresentationClock(
        phase=phase,
        elapsed_seconds=elapsed,
        remaining_seconds=max(0, math.ceil(duration_seconds - elapsed)),
        football_second=football_second,
        complete=phase == "complete",
    )


def event_is_visible(event: dict[str, object], clock: PresentationClock) -> bool:
    if clock.complete:
        return True
    minute_value = event.get("minute", 0)
    second_value = event.get("second", 0)
    if not isinstance(minute_value, (int, float)) or not isinstance(second_value, (int, float)):
        return False
    minute = int(minute_value)
    second = int(second_value)
    return bool(minute * 60 + second <= clock.football_second)
