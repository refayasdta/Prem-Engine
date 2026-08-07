"""Tolerant v2 DTOs isolated from the canonical football domain."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderTeam(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    country: str | None = None
    logo: str | None = None


class ProviderLeague(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    season: int | None = None
    country: str | None = None
    logo: str | None = None


class ProviderStatus(BaseModel):
    model_config = ConfigDict(extra="allow")

    long: str | None = None
    short: str | None = None
    elapsed: int | None = None


class ProviderScore(BaseModel):
    model_config = ConfigDict(extra="allow")

    home: int | None = None
    away: int | None = None


class ProviderFixture(BaseModel):
    """Accept both fixture shapes currently shown in KickoffAPI's official v2 docs."""

    model_config = ConfigDict(extra="allow")

    id: str
    date: datetime
    league: ProviderLeague
    home: ProviderTeam | None = None
    away: ProviderTeam | None = None
    home_team: ProviderTeam | None = Field(default=None, alias="homeTeam")
    away_team: ProviderTeam | None = Field(default=None, alias="awayTeam")
    status: ProviderStatus | str
    score: ProviderScore | None = None
    home_score: int | None = Field(default=None, alias="homeScore")
    away_score: int | None = Field(default=None, alias="awayScore")

    @model_validator(mode="after")
    def require_teams(self) -> ProviderFixture:
        if self.home is None and self.home_team is None:
            raise ValueError("fixture has no home team")
        if self.away is None and self.away_team is None:
            raise ValueError("fixture has no away team")
        return self

    @property
    def normalized_home(self) -> ProviderTeam:
        team = self.home or self.home_team
        if team is None:  # pragma: no cover - guarded by validation
            raise ValueError("fixture has no home team")
        return team

    @property
    def normalized_away(self) -> ProviderTeam:
        team = self.away or self.away_team
        if team is None:  # pragma: no cover - guarded by validation
            raise ValueError("fixture has no away team")
        return team

    @property
    def status_code(self) -> str:
        if isinstance(self.status, str):
            return self.status
        return self.status.short or self.status.long or "unknown"

    @property
    def normalized_home_score(self) -> int | None:
        return self.score.home if self.score is not None else self.home_score

    @property
    def normalized_away_score(self) -> int | None:
        return self.score.away if self.score is not None else self.away_score


class FixtureEnvelope(BaseModel):
    """Support both documented v2 pagination-envelope variants."""

    model_config = ConfigDict(extra="allow")

    data: list[ProviderFixture]
    meta: dict[str, Any] = Field(default_factory=dict)
    count: int | None = None
    page: int | None = None
    total_pages: int | None = Field(default=None, alias="totalPages")


class LeagueEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: list[ProviderLeague]
    meta: dict[str, Any] = Field(default_factory=dict)
    count: int | None = None


class TeamEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: list[ProviderTeam]
    meta: dict[str, Any] = Field(default_factory=dict)
    count: int | None = None


def validate_endpoint_payload(endpoint: str, payload: object) -> BaseModel:
    """Validate a captured payload without leaking provider values into the domain."""

    validators: dict[str, type[BaseModel]] = {
        "/api/v2/leagues": LeagueEnvelope,
        "/api/v2/teams": TeamEnvelope,
        "/api/v2/fixtures": FixtureEnvelope,
    }
    validator = validators.get(endpoint)
    if validator is None:
        raise ValueError(f"no contract validator registered for {endpoint}")
    return validator.model_validate(payload)
