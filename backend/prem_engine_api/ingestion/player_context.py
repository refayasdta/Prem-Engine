"""Normalize current KickoffAPI player context into canonical domain records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.enums import PlayerAvailabilityStatus
from prem_engine_api.domain.models import (
    ClubExternalReference,
    MatchExternalReference,
    ObservedLineup,
    ObservedLineupPlayer,
    Player,
    PlayerAvailabilityReport,
    PlayerExternalReference,
    PlayerMatchPerformance,
    Season,
    SquadMembership,
    TransferObservation,
)
from prem_engine_api.providers.kickoffapi.contracts import (
    FixturePlayerEnvelope,
    InjuryEnvelope,
    LineupEnvelope,
    ProviderPlayer,
    SquadEnvelope,
    TransferEnvelope,
)

PROVIDER = "kickoffapi"


class PlayerContextIngestionError(RuntimeError):
    """Raised when provider data cannot be mapped without inventing identity."""


@dataclass(frozen=True)
class PlayerContextIngestionSummary:
    received: int
    created: int
    updated: int
    unchanged: int
    unresolved: int


def _birth_date(value: date | dict[str, Any] | None) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, dict):
        raw = value.get("date")
        if isinstance(raw, str):
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                return None
    return None


def _player_name(player: ProviderPlayer) -> str | None:
    direct = (player.name or "").strip()
    if direct:
        return direct
    combined = " ".join(
        part.strip() for part in (player.firstname or "", player.lastname or "") if part.strip()
    )
    return combined or None


def _checksum(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _availability(reason: str | None) -> tuple[PlayerAvailabilityStatus, Decimal]:
    normalized = (reason or "").casefold()
    if "suspend" in normalized or "ban" in normalized:
        return PlayerAvailabilityStatus.SUSPENDED, Decimal("0.0000")
    if "doubt" in normalized or "test" in normalized:
        return PlayerAvailabilityStatus.DOUBTFUL, Decimal("0.5000")
    if normalized:
        return PlayerAvailabilityStatus.OUT, Decimal("0.0000")
    return PlayerAvailabilityStatus.UNKNOWN, Decimal("0.7500")


def _datetime(value: date | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return None


class PlayerContextIngestor:
    """Idempotently ingest provider captures inside the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _player(self, provider_player: ProviderPlayer, observed_at: datetime) -> Player:
        reference = await self._session.scalar(
            select(PlayerExternalReference).where(
                PlayerExternalReference.provider == PROVIDER,
                PlayerExternalReference.external_player_id == provider_player.id,
            )
        )
        name = _player_name(provider_player)
        if reference is not None:
            player = await self._session.get(Player, reference.player_uuid)
            if player is None:
                raise PlayerContextIngestionError("player reference points to a missing player")
            if name:
                player.canonical_name = name
            player.birth_date = _birth_date(provider_player.birth) or player.birth_date
            player.photo_url = provider_player.photo or player.photo_url
            return player
        if name is None:
            raise PlayerContextIngestionError(
                f"provider player {provider_player.id!r} has no usable name"
            )
        player = Player(
            canonical_name=name,
            birth_date=_birth_date(provider_player.birth),
            photo_url=provider_player.photo,
        )
        self._session.add(player)
        await self._session.flush()
        self._session.add(
            PlayerExternalReference(
                player_uuid=player.player_uuid,
                provider=PROVIDER,
                external_player_id=provider_player.id,
                observed_from=observed_at,
            )
        )
        return player

    async def _club_uuid(self, external_id: str | None) -> Any:
        if not external_id:
            return None
        reference = await self._session.scalar(
            select(ClubExternalReference).where(
                ClubExternalReference.provider == PROVIDER,
                ClubExternalReference.external_club_id == external_id,
            )
        )
        return reference.club_uuid if reference is not None else None

    async def ingest_squad(
        self,
        payload: object,
        *,
        season_uuid: Any,
        club_uuid: Any,
        observed_at: datetime,
    ) -> PlayerContextIngestionSummary:
        envelope = SquadEnvelope.model_validate(payload)
        season = await self._session.get(Season, season_uuid)
        if season is None:
            raise PlayerContextIngestionError("squad season does not exist")
        created = updated = unchanged = unresolved = 0
        for provider_player in envelope.data:
            try:
                player = await self._player(provider_player, observed_at)
            except PlayerContextIngestionError:
                unresolved += 1
                continue
            membership = await self._session.scalar(
                select(SquadMembership).where(
                    SquadMembership.season_uuid == season_uuid,
                    SquadMembership.club_uuid == club_uuid,
                    SquadMembership.player_uuid == player.player_uuid,
                    SquadMembership.left_on.is_(None),
                )
            )
            if membership is None:
                self._session.add(
                    SquadMembership(
                        season_uuid=season_uuid,
                        club_uuid=club_uuid,
                        player_uuid=player.player_uuid,
                        joined_on=max(season.start_date, observed_at.date()),
                        shirt_number=provider_player.number,
                        primary_position=provider_player.position,
                    )
                )
                created += 1
            elif (
                membership.shirt_number != provider_player.number
                or membership.primary_position != provider_player.position
            ):
                membership.shirt_number = provider_player.number
                membership.primary_position = provider_player.position
                membership.updated_at = observed_at
                updated += 1
            else:
                membership.updated_at = observed_at
                unchanged += 1
        await self._session.flush()
        return PlayerContextIngestionSummary(
            len(envelope.data), created, updated, unchanged, unresolved
        )

    async def ingest_injuries(
        self, payload: object, *, observed_at: datetime, provider_payload_key: str
    ) -> PlayerContextIngestionSummary:
        envelope = InjuryEnvelope.model_validate(payload)
        created = unchanged = unresolved = 0
        for index, injury in enumerate(envelope.data):
            try:
                player = await self._player(injury.player, observed_at)
            except PlayerContextIngestionError:
                unresolved += 1
                continue
            club_uuid = await self._club_uuid(injury.team.id if injury.team else None)
            if club_uuid is None:
                membership = await self._session.scalar(
                    select(SquadMembership)
                    .where(
                        SquadMembership.player_uuid == player.player_uuid,
                        SquadMembership.left_on.is_(None),
                    )
                    .order_by(SquadMembership.updated_at.desc())
                    .limit(1)
                )
                club_uuid = membership.club_uuid if membership is not None else None
            if club_uuid is None:
                unresolved += 1
                continue
            match_uuid = None
            fixture = injury.fixture or {}
            fixture_id = fixture.get("id")
            if fixture_id is not None:
                match_reference = await self._session.scalar(
                    select(MatchExternalReference).where(
                        MatchExternalReference.provider == PROVIDER,
                        MatchExternalReference.external_fixture_id == str(fixture_id),
                    )
                )
                match_uuid = match_reference.match_uuid if match_reference else None
            source_key = f"{provider_payload_key}:injury:{injury.id or index}"
            existing = await self._session.scalar(
                select(PlayerAvailabilityReport).where(
                    PlayerAvailabilityReport.provider == PROVIDER,
                    PlayerAvailabilityReport.provider_payload_key == source_key,
                    PlayerAvailabilityReport.player_uuid == player.player_uuid,
                    PlayerAvailabilityReport.match_uuid == match_uuid,
                )
            )
            if existing is not None:
                unchanged += 1
                continue
            detail = injury.injury
            reason = injury.reason or injury.type or (detail.type if detail else None)
            status, probability = _availability(reason)
            self._session.add(
                PlayerAvailabilityReport(
                    player_uuid=player.player_uuid,
                    club_uuid=club_uuid,
                    match_uuid=match_uuid,
                    status=status,
                    reason=reason,
                    availability_probability=probability,
                    reported_at=_datetime(injury.reported_at),
                    expected_return_at=(
                        _datetime(injury.expected_return)
                        or _datetime(detail.until if detail else None)
                    ),
                    observed_at=observed_at,
                    provider=PROVIDER,
                    provider_payload_key=source_key,
                )
            )
            created += 1
        await self._session.flush()
        return PlayerContextIngestionSummary(len(envelope.data), created, 0, unchanged, unresolved)

    async def ingest_transfers(
        self, payload: object, *, observed_at: datetime, provider_payload_key: str
    ) -> PlayerContextIngestionSummary:
        envelope = TransferEnvelope.model_validate(payload)
        created = unchanged = unresolved = 0
        for index, transfer in enumerate(envelope.data):
            try:
                player = await self._player(transfer.player, observed_at)
            except PlayerContextIngestionError:
                unresolved += 1
                continue
            teams = transfer.teams or {}
            incoming = (
                cast(dict[str, Any], teams.get("in")) if isinstance(teams.get("in"), dict) else {}
            )
            outgoing = (
                cast(dict[str, Any], teams.get("out")) if isinstance(teams.get("out"), dict) else {}
            )
            from_uuid = await self._club_uuid(
                str(outgoing.get("id")) if outgoing.get("id") else None
            )
            to_uuid = await self._club_uuid(str(incoming.get("id")) if incoming.get("id") else None)
            external_id = str(transfer.id) if transfer.id is not None else None
            existing = await self._session.scalar(
                select(TransferObservation).where(
                    TransferObservation.provider == PROVIDER,
                    TransferObservation.player_uuid == player.player_uuid,
                    TransferObservation.external_transfer_id == external_id,
                    TransferObservation.transfer_date == transfer.date,
                    TransferObservation.from_club_uuid == from_uuid,
                    TransferObservation.to_club_uuid == to_uuid,
                )
            )
            if existing is not None:
                unchanged += 1
                continue
            self._session.add(
                TransferObservation(
                    player_uuid=player.player_uuid,
                    from_club_uuid=from_uuid,
                    to_club_uuid=to_uuid,
                    transfer_date=transfer.date,
                    transfer_type=transfer.type,
                    external_transfer_id=external_id,
                    observed_at=observed_at,
                    provider=PROVIDER,
                    provider_payload_key=f"{provider_payload_key}:transfer:{external_id or index}",
                )
            )
            created += 1
        await self._session.flush()
        return PlayerContextIngestionSummary(len(envelope.data), created, 0, unchanged, unresolved)

    async def ingest_lineups(
        self,
        payload: object,
        *,
        match_uuid: Any,
        observed_at: datetime,
        provider_payload_key: str,
    ) -> PlayerContextIngestionSummary:
        envelope = LineupEnvelope.model_validate(payload)
        created = unchanged = unresolved = received = 0
        for lineup in envelope.data:
            club_uuid = await self._club_uuid(lineup.team.id)
            if club_uuid is None:
                unresolved += 1
                continue
            serialized = lineup.model_dump(mode="json", by_alias=True)
            checksum = _checksum(serialized)
            existing = await self._session.scalar(
                select(ObservedLineup).where(
                    ObservedLineup.match_uuid == match_uuid,
                    ObservedLineup.club_uuid == club_uuid,
                    ObservedLineup.checksum == checksum,
                )
            )
            slots = [("starter", item) for item in lineup.start_xi]
            slots.extend(("substitute", item) for item in lineup.substitutes)
            received += len(slots)
            if existing is not None:
                unchanged += len(slots)
                continue
            observed = ObservedLineup(
                match_uuid=match_uuid,
                club_uuid=club_uuid,
                formation=lineup.formation,
                confirmed=True,
                observed_at=observed_at,
                available_after=observed_at,
                provider=PROVIDER,
                provider_payload_key=provider_payload_key,
                checksum=checksum,
            )
            self._session.add(observed)
            await self._session.flush()
            role_slots = {"starter": 0, "substitute": 0}
            for role, slot in slots:
                role_slots[role] += 1
                try:
                    player = await self._player(slot.player, observed_at)
                except PlayerContextIngestionError:
                    unresolved += 1
                    continue
                self._session.add(
                    ObservedLineupPlayer(
                        observed_lineup_uuid=observed.observed_lineup_uuid,
                        player_uuid=player.player_uuid,
                        role=role,
                        slot=role_slots[role],
                        position=slot.position,
                        shirt_number=slot.number,
                    )
                )
                created += 1
        await self._session.flush()
        return PlayerContextIngestionSummary(received, created, 0, unchanged, unresolved)

    async def ingest_performances(
        self,
        payload: object,
        *,
        match_uuid: Any,
        observed_at: datetime,
        provider_payload_key: str,
    ) -> PlayerContextIngestionSummary:
        envelope = FixturePlayerEnvelope.model_validate(payload)
        entries: list[tuple[dict[str, Any] | None, dict[str, Any]]] = []
        for block in envelope.data:
            nested = block.get("players")
            if isinstance(nested, list):
                entries.extend(
                    (block.get("team"), item) for item in nested if isinstance(item, dict)
                )
            else:
                entries.append((block.get("team"), block))
        created = updated = unchanged = unresolved = 0
        for team_data, entry in entries:
            raw_player = entry.get("player")
            if not isinstance(raw_player, dict):
                unresolved += 1
                continue
            try:
                provider_player = ProviderPlayer.model_validate(raw_player)
                player = await self._player(provider_player, observed_at)
            except (ValueError, PlayerContextIngestionError):
                unresolved += 1
                continue
            team_id = team_data.get("id") if isinstance(team_data, dict) else entry.get("team_id")
            club_uuid = await self._club_uuid(str(team_id) if team_id is not None else None)
            if club_uuid is None:
                unresolved += 1
                continue
            statistics_value = entry.get("statistics")
            if isinstance(statistics_value, list):
                statistics = statistics_value[0] if statistics_value else {}
            else:
                statistics = statistics_value if isinstance(statistics_value, dict) else {}
            games = (
                cast(dict[str, Any], statistics.get("games"))
                if isinstance(statistics.get("games"), dict)
                else {}
            )
            minutes = games.get("minutes", statistics.get("minutes"))
            rating = games.get("rating", statistics.get("rating"))
            substitute = games.get("substitute")
            started = None if substitute is None else not bool(substitute)
            position = games.get("position", provider_player.position)
            existing = await self._session.scalar(
                select(PlayerMatchPerformance).where(
                    PlayerMatchPerformance.match_uuid == match_uuid,
                    PlayerMatchPerformance.club_uuid == club_uuid,
                    PlayerMatchPerformance.player_uuid == player.player_uuid,
                )
            )
            values = {
                "started": started,
                "starting_status_source": "observed" if started is not None else "unknown",
                "position": str(position) if position is not None else None,
                "minutes": int(minutes) if minutes is not None else None,
                "rating": Decimal(str(rating)) if rating not in (None, "") else None,
                "statistics": statistics,
                "available_after": observed_at,
                "provider_payload_key": f"{provider_payload_key}:performance:{provider_player.id}",
            }
            if existing is None:
                self._session.add(
                    PlayerMatchPerformance(
                        match_uuid=match_uuid,
                        club_uuid=club_uuid,
                        player_uuid=player.player_uuid,
                        provider=PROVIDER,
                        **values,
                    )
                )
                created += 1
            elif any(getattr(existing, key) != value for key, value in values.items()):
                for key, value in values.items():
                    setattr(existing, key, value)
                updated += 1
            else:
                unchanged += 1
        await self._session.flush()
        return PlayerContextIngestionSummary(len(entries), created, updated, unchanged, unresolved)
