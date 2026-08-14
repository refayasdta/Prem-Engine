"""Tolerant v2 DTOs isolated from the canonical football domain."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderTeam(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    country: str | None = None
    logo: str | None = None


class ProviderPlayer(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str | None = None
    firstname: str | None = None
    lastname: str | None = None
    birth: date | dict[str, Any] | None = None
    nationality: str | None = None
    position: str | None = None
    photo: str | None = None


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
    round: str | None = None
    group: str | None = None

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


class PlayerEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: list[ProviderPlayer]
    meta: dict[str, Any] = Field(default_factory=dict)
    count: int | None = None


class ProviderSquadPlayer(ProviderPlayer):
    number: int | None = None


class SquadEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: list[ProviderSquadPlayer]
    meta: dict[str, Any] = Field(default_factory=dict)


class ProviderLineupSlot(BaseModel):
    model_config = ConfigDict(extra="allow")

    player: ProviderPlayer
    position: str | None = Field(default=None, alias="pos")
    grid: str | None = None
    number: int | None = None


class ProviderLineup(BaseModel):
    model_config = ConfigDict(extra="allow")

    team: ProviderTeam
    formation: str | None = None
    start_xi: list[ProviderLineupSlot] = Field(default_factory=list, alias="startXI")
    substitutes: list[ProviderLineupSlot] = Field(default_factory=list)


class LineupEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: list[ProviderLineup]
    meta: dict[str, Any] = Field(default_factory=dict)


class ProviderInjuryDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str | None = None
    from_date: date | datetime | None = Field(default=None, alias="from")
    until: date | datetime | None = None


class ProviderInjury(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | int | None = None
    reason: str | None = None
    type: str | None = None
    player: ProviderPlayer
    injury: ProviderInjuryDetail | None = None
    team: ProviderTeam | None = None
    fixture: dict[str, Any] | None = None
    reported_at: datetime | None = Field(default=None, alias="reportedAt")
    expected_return: datetime | None = Field(default=None, alias="expectedReturn")


class InjuryEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: list[ProviderInjury]
    meta: dict[str, Any] = Field(default_factory=dict)


class ProviderTransfer(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | int | None = None
    date: date
    type: str | None = None
    player: ProviderPlayer | None = None
    player_id: str | int | None = Field(default=None, alias="playerId")
    teams: dict[str, Any] | None = None
    team_in_id: str | int | None = Field(default=None, alias="teamInId")
    team_out_id: str | int | None = Field(default=None, alias="teamOutId")

    @model_validator(mode="after")
    def require_player_reference(self) -> ProviderTransfer:
        if self.player is None and self.player_id is None:
            raise ValueError("transfer has no player reference")
        return self

    @property
    def normalized_player(self) -> ProviderPlayer:
        if self.player is not None:
            return self.player
        return ProviderPlayer(id=str(self.player_id))

    @property
    def normalized_teams(self) -> tuple[str | None, str | None]:
        teams = self.teams or {}
        incoming = teams.get("in") if isinstance(teams.get("in"), dict) else {}
        outgoing = teams.get("out") if isinstance(teams.get("out"), dict) else {}
        from_id = self.team_out_id or cast(dict[str, Any], outgoing).get("id")
        to_id = self.team_in_id or cast(dict[str, Any], incoming).get("id")
        return (
            str(from_id) if from_id is not None else None,
            str(to_id) if to_id is not None else None,
        )


class TransferEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: list[ProviderTransfer]
    meta: dict[str, Any] = Field(default_factory=dict)


class FixturePlayerEnvelope(BaseModel):
    """Player-stat shapes vary by source, so preserve typed object boundaries."""

    model_config = ConfigDict(extra="allow")

    data: list[dict[str, Any]]
    meta: dict[str, Any] = Field(default_factory=dict)


def validate_endpoint_payload(endpoint: str, payload: object) -> BaseModel:
    """Validate a captured payload without leaking provider values into the domain."""

    validators: dict[str, type[BaseModel]] = {
        "/api/v2/leagues": LeagueEnvelope,
        "/api/v2/teams": TeamEnvelope,
        "/api/v2/fixtures": FixtureEnvelope,
        "/api/v2/players": PlayerEnvelope,
        "/api/v2/injuries": InjuryEnvelope,
        "/api/v2/transfers": TransferEnvelope,
    }
    validator = validators.get(endpoint)
    route_parts = endpoint.strip("/").split("/")
    if len(route_parts) == 5 and route_parts[:3] == ["api", "v2", "teams"]:
        if route_parts[4] == "squad":
            validator = SquadEnvelope
    if len(route_parts) == 5 and route_parts[:3] == ["api", "v2", "fixtures"]:
        if route_parts[4] == "lineups":
            validator = LineupEnvelope
        elif route_parts[4] == "players":
            validator = FixturePlayerEnvelope
    if validator is None:
        raise ValueError(f"no contract validator registered for {endpoint}")
    return validator.model_validate(payload)
