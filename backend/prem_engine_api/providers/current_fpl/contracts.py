"""Validated subset of the official FPL bootstrap contract."""

from pydantic import BaseModel, ConfigDict, Field


class CurrentFplTeam(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str = Field(min_length=1)
    short_name: str = Field(min_length=1)


class CurrentFplPlayer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    first_name: str = ""
    second_name: str = ""
    web_name: str = Field(min_length=1)
    team: int
    element_type: int = Field(ge=1, le=4)
    squad_number: int | None = None

    @property
    def canonical_name(self) -> str:
        full_name = " ".join(
            part.strip() for part in (self.first_name, self.second_name) if part.strip()
        )
        return full_name or self.web_name.strip()


class CurrentFplBootstrap(BaseModel):
    model_config = ConfigDict(extra="ignore")

    teams: list[CurrentFplTeam]
    elements: list[CurrentFplPlayer]
