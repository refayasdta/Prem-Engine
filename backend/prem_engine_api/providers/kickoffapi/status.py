"""Map provider fixture statuses while retaining their original values."""

from prem_engine_api.domain.enums import FixtureStatus

STATUS_MAP = {
    "NS": FixtureStatus.SCHEDULED,
    "TBD": FixtureStatus.SCHEDULED,
    "scheduled": FixtureStatus.SCHEDULED,
    "PST": FixtureStatus.POSTPONED,
    "postponed": FixtureStatus.POSTPONED,
    "CANC": FixtureStatus.CANCELLED,
    "cancelled": FixtureStatus.CANCELLED,
    "1H": FixtureStatus.STARTED,
    "HT": FixtureStatus.STARTED,
    "2H": FixtureStatus.STARTED,
    "ET": FixtureStatus.STARTED,
    "P": FixtureStatus.STARTED,
    "live": FixtureStatus.STARTED,
    "INT": FixtureStatus.SUSPENDED,
    "SUSP": FixtureStatus.SUSPENDED,
    "suspended": FixtureStatus.SUSPENDED,
    "FT": FixtureStatus.FINISHED,
    "AET": FixtureStatus.FINISHED,
    "PEN": FixtureStatus.FINISHED,
    "finished": FixtureStatus.FINISHED,
    "ABD": FixtureStatus.ABANDONED,
    "abandoned": FixtureStatus.ABANDONED,
    "AWD": FixtureStatus.AWARDED,
    "WO": FixtureStatus.AWARDED,
    "awarded": FixtureStatus.AWARDED,
}


def map_fixture_status(provider_status: str) -> FixtureStatus:
    """Return a safe canonical state; unknown values require later review."""

    return STATUS_MAP.get(provider_status, FixtureStatus.SCHEDULED)
