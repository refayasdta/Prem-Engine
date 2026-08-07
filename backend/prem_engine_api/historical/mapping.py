"""Reviewed aliases that bridge source-specific club names to canonical identities."""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.models import Club, ClubAlias


class ClubMappingError(ValueError):
    """Raised when a club alias is absent or conflicts with reviewed mapping data."""


@dataclass(frozen=True)
class ReviewedClubAlias:
    source_alias: str
    canonical_name: str
    short_name: str
    active: bool


def normalize_club_alias(value: str) -> str:
    """Return a stable comparison key without performing unsafe fuzzy matching."""

    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "", ascii_value.casefold())


def load_reviewed_aliases(path: Path) -> tuple[ReviewedClubAlias, ...]:
    """Load the repository-reviewed alias registry."""

    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"source_alias", "canonical_name", "short_name", "active"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ClubMappingError("club alias registry has an invalid header")
        aliases = tuple(
            ReviewedClubAlias(
                source_alias=(row["source_alias"] or "").strip(),
                canonical_name=(row["canonical_name"] or "").strip(),
                short_name=(row["short_name"] or "").strip(),
                active=(row["active"] or "").strip().casefold() == "true",
            )
            for row in reader
        )
    if not aliases or any(
        not alias.source_alias or not alias.canonical_name or not alias.short_name
        for alias in aliases
    ):
        raise ClubMappingError("club alias registry contains blank required values")
    normalized = [normalize_club_alias(alias.source_alias) for alias in aliases]
    if len(normalized) != len(set(normalized)):
        raise ClubMappingError("club alias registry contains duplicate normalized aliases")
    return aliases


async def seed_reviewed_aliases(
    session: AsyncSession,
    *,
    provider: str,
    registry_path: Path,
    reviewed_at: datetime | None = None,
) -> dict[str, Club]:
    """Create canonical clubs and source aliases solely from the reviewed registry."""

    aliases = load_reviewed_aliases(registry_path)
    observed_at = reviewed_at or datetime.now(UTC)
    resolved: dict[str, Club] = {}
    for definition in aliases:
        club = await session.scalar(
            select(Club).where(Club.canonical_name == definition.canonical_name)
        )
        if club is None:
            club = Club(
                canonical_name=definition.canonical_name,
                short_name=definition.short_name,
                active=definition.active,
            )
            session.add(club)
            await session.flush()

        normalized = normalize_club_alias(definition.source_alias)
        existing = await session.scalar(
            select(ClubAlias).where(
                ClubAlias.provider == provider,
                ClubAlias.normalized_alias == normalized,
            )
        )
        if existing is None:
            session.add(
                ClubAlias(
                    club_uuid=club.club_uuid,
                    provider=provider,
                    alias=definition.source_alias,
                    normalized_alias=normalized,
                    reviewed_by="repository-reviewed-registry",
                    reviewed_at=observed_at,
                )
            )
        elif existing.club_uuid != club.club_uuid:
            raise ClubMappingError(f"reviewed alias changed identity: {definition.source_alias}")
        resolved[normalized] = club
    await session.flush()
    return resolved


def resolve_club(clubs_by_alias: dict[str, Club], source_name: str) -> Club:
    """Resolve exactly or fail; unresolved names must never create guessed identities."""

    normalized = normalize_club_alias(source_name)
    try:
        return clubs_by_alias[normalized]
    except KeyError as error:
        raise ClubMappingError(f"unreviewed club alias: {source_name}") from error
