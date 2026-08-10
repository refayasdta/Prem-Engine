"""Minimal response contracts for the API-Football coverage audit."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Paging(BaseModel):
    """Pagination metadata returned with every API-Football envelope."""

    current: int = 1
    total: int = 1


class ApiFootballEnvelope(BaseModel):
    """Provider envelope without coupling the domain to endpoint-specific values."""

    get: str
    parameters: dict[str, Any] | list[Any] = Field(default_factory=dict)
    errors: dict[str, Any] | list[Any] = Field(default_factory=dict)
    results: int = 0
    paging: Paging = Field(default_factory=Paging)
    response: list[Any] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")

    @property
    def has_errors(self) -> bool:
        """Return whether the provider envelope contains one or more errors."""

        return bool(self.errors)


def provider_error_keys(envelope: ApiFootballEnvelope) -> list[str]:
    """Describe error categories without copying provider messages into evidence."""

    if isinstance(envelope.errors, dict):
        return sorted(str(key) for key in envelope.errors)
    return ["unstructured_error"] if envelope.errors else []


def first_fixture_id(envelope: ApiFootballEnvelope) -> int | None:
    """Extract one fixture identifier for dependent audit calls."""

    if not envelope.response or not isinstance(envelope.response[0], dict):
        return None
    fixture = envelope.response[0].get("fixture")
    if not isinstance(fixture, dict):
        return None
    value = fixture.get("id")
    return value if isinstance(value, int) else None


def league_coverage(envelope: ApiFootballEnvelope, season: int) -> dict[str, bool | None]:
    """Extract only the public coverage flags needed to judge model readiness."""

    empty: dict[str, bool | None] = {
        "lineups": None,
        "fixture_statistics": None,
        "player_statistics": None,
        "players": None,
        "injuries": None,
    }
    if not envelope.response or not isinstance(envelope.response[0], dict):
        return empty
    seasons = envelope.response[0].get("seasons")
    if not isinstance(seasons, list):
        return empty
    selected = next(
        (item for item in seasons if isinstance(item, dict) and item.get("year") == season),
        None,
    )
    if not isinstance(selected, dict):
        return empty
    coverage = selected.get("coverage")
    if not isinstance(coverage, dict):
        return empty
    fixtures = coverage.get("fixtures")
    fixture_coverage = fixtures if isinstance(fixtures, dict) else {}

    def flag(container: dict[str, Any], key: str) -> bool | None:
        value = container.get(key)
        return value if isinstance(value, bool) else None

    return {
        "lineups": flag(fixture_coverage, "lineups"),
        "fixture_statistics": flag(fixture_coverage, "statistics_fixtures"),
        "player_statistics": flag(fixture_coverage, "statistics_players"),
        "players": flag(coverage, "players"),
        "injuries": flag(coverage, "injuries"),
    }
