"""Fixed one-minute presentation clock and leakage tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from prem_engine_api.forecasting.presentation import event_is_visible, presentation_clock


def test_one_minute_clock_uses_25_10_25_timing() -> None:
    started = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

    first_half = presentation_clock(
        started_at=started, duration_seconds=60, now=started + timedelta(seconds=12.5)
    )
    interval = presentation_clock(
        started_at=started, duration_seconds=60, now=started + timedelta(seconds=30)
    )
    second_half = presentation_clock(
        started_at=started, duration_seconds=60, now=started + timedelta(seconds=47.5)
    )
    complete = presentation_clock(
        started_at=started, duration_seconds=60, now=started + timedelta(seconds=60)
    )

    assert first_half.phase == "first_half"
    assert first_half.football_second == 1350
    assert interval.phase == "half_time"
    assert interval.football_second == 2700
    assert second_half.phase == "second_half"
    assert second_half.football_second == 4050
    assert complete.phase == "complete"
    assert complete.football_second == 5400


def test_countdown_and_event_visibility_do_not_reveal_the_future() -> None:
    started = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    countdown = presentation_clock(
        started_at=started, duration_seconds=60, now=started - timedelta(seconds=9.2)
    )
    first_half = presentation_clock(
        started_at=started, duration_seconds=60, now=started + timedelta(seconds=10)
    )

    assert countdown.phase == "countdown"
    assert countdown.remaining_seconds == 10
    assert event_is_visible({"minute": 10, "second": 0}, first_half)
    assert not event_is_visible({"minute": 30, "second": 0}, first_half)
