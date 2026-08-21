"""Map current official FPL squads onto existing canonical clubs and players."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.models import (
    Club,
    ClubExternalReference,
    Player,
    PlayerExternalReference,
    Season,
    SquadMembership,
)
from prem_engine_api.ingestion.player_context import PlayerContextIngestionSummary
from prem_engine_api.providers.current_fpl.contracts import CurrentFplBootstrap, CurrentFplPlayer

PROVIDER = "fpl-current"
POSITIONS = {1: "Goalkeeper", 2: "Defender", 3: "Midfielder", 4: "Attacker"}


def _aliases(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            row["source_alias"].casefold(): row["canonical_name"] for row in csv.DictReader(handle)
        }


def _club_key(value: str) -> str:
    normalized = " ".join(value.casefold().split())
    return normalized[:-3] if normalized.endswith(" fc") else normalized


async def ingest_current_fpl_squads(
    session: AsyncSession,
    payload: object,
    *,
    season_uuid: UUID,
    target_club_uuids: set[UUID],
    observed_at: datetime,
    mapping_path: Path = Path("data/mappings/fpl-clubs.csv"),
) -> PlayerContextIngestionSummary:
    bootstrap = CurrentFplBootstrap.model_validate(payload)
    season = await session.get(Season, season_uuid)
    if season is None:
        raise RuntimeError("FPL squad season does not exist")
    aliases = _aliases(mapping_path)
    clubs = {
        _club_key(club.canonical_name): club
        for club in (
            await session.scalars(select(Club).where(Club.club_uuid.in_(target_club_uuids)))
        ).all()
    }
    team_to_club: dict[int, Club] = {}
    unresolved = 0
    for team in bootstrap.teams:
        canonical = aliases.get(team.name.casefold())
        club = clubs.get(_club_key(canonical or ""))
        if club is None:
            continue
        team_to_club[team.id] = club
        reference = await session.scalar(
            select(ClubExternalReference).where(
                ClubExternalReference.provider == PROVIDER,
                ClubExternalReference.external_club_id == str(team.id),
            )
        )
        if reference is None:
            session.add(
                ClubExternalReference(
                    club_uuid=club.club_uuid,
                    provider=PROVIDER,
                    external_club_id=str(team.id),
                    observed_from=observed_at,
                )
            )
    created = updated = unchanged = received = 0
    for source in bootstrap.elements:
        club = team_to_club.get(source.team)
        if club is None:
            continue
        received += 1
        player = await _resolve_player(session, source, club.club_uuid, season_uuid, observed_at)
        membership = await session.scalar(
            select(SquadMembership).where(
                SquadMembership.season_uuid == season_uuid,
                SquadMembership.club_uuid == club.club_uuid,
                SquadMembership.player_uuid == player.player_uuid,
                SquadMembership.left_on.is_(None),
            )
        )
        position = POSITIONS[source.element_type]
        if membership is None:
            session.add(
                SquadMembership(
                    season_uuid=season_uuid,
                    club_uuid=club.club_uuid,
                    player_uuid=player.player_uuid,
                    joined_on=season.start_date,
                    shirt_number=source.squad_number,
                    primary_position=position,
                )
            )
            created += 1
        elif (
            membership.shirt_number != source.squad_number
            or membership.primary_position != position
        ):
            membership.shirt_number = source.squad_number
            membership.primary_position = position
            membership.updated_at = observed_at
            updated += 1
        else:
            membership.updated_at = observed_at
            unchanged += 1
    await session.flush()
    return PlayerContextIngestionSummary(received, created, updated, unchanged, unresolved)


async def _resolve_player(
    session: AsyncSession,
    source: CurrentFplPlayer,
    club_uuid: UUID,
    season_uuid: UUID,
    observed_at: datetime,
) -> Player:
    reference = await session.scalar(
        select(PlayerExternalReference).where(
            PlayerExternalReference.provider == PROVIDER,
            PlayerExternalReference.external_player_id == str(source.id),
        )
    )
    if reference is not None:
        player = await session.get(Player, reference.player_uuid)
        if player is None:
            raise RuntimeError("FPL player reference points to a missing player")
        player.canonical_name = source.canonical_name
        return player
    candidates = (
        await session.scalars(
            select(Player)
            .join(SquadMembership, SquadMembership.player_uuid == Player.player_uuid)
            .where(
                SquadMembership.season_uuid == season_uuid,
                SquadMembership.club_uuid == club_uuid,
                SquadMembership.left_on.is_(None),
                Player.canonical_name == source.canonical_name,
            )
        )
    ).all()
    player = candidates[0] if len(candidates) == 1 else Player(canonical_name=source.canonical_name)
    if len(candidates) != 1:
        session.add(player)
        await session.flush()
    session.add(
        PlayerExternalReference(
            player_uuid=player.player_uuid,
            provider=PROVIDER,
            external_player_id=str(source.id),
            observed_from=observed_at,
        )
    )
    return player
