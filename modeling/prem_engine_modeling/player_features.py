"""Leakage-safe player strength, expected-lineup, and availability features."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from prem_engine_modeling.feature_export import validate_feature_export
from prem_engine_modeling.features import (
    IDENTITY_COLUMNS,
    PREMATCH_FEATURE_COLUMNS,
    TARGET_COLUMNS,
)
from prem_engine_modeling.player_data import (
    AvailabilityObservation,
    AvailabilityStatus,
    PlayerContextDataset,
    PlayerPerformance,
    PlayerPosition,
    TransferObservation,
)

PLAYER_FEATURE_CONTRACT_VERSION = "player-context-features-v1"
UNKNOWN_AVAILABILITY_PROBABILITY = 0.75
# A full-season window preserves players across the summer break; transfer observations
# explicitly remove departures when they are known.
RECENT_SQUAD_WINDOW = timedelta(days=400)
TRANSFER_UNCERTAINTY_WINDOW = timedelta(days=90)
FORMATION_REQUIREMENTS: dict[PlayerPosition, int] = {
    "goalkeeper": 1,
    "defender": 4,
    "midfielder": 3,
    "attacker": 3,
}


@dataclass(frozen=True)
class PlayerProfile:
    player_uuid: str
    position: PlayerPosition
    appearances: int
    starting_probability: float
    strength: float
    strength_confidence: float
    availability_status: AvailabilityStatus
    availability_probability: float
    availability_known: bool
    transferred_recently: bool

    @property
    def selection_score(self) -> float:
        return self.starting_probability * self.availability_probability


@dataclass(frozen=True)
class ExpectedLineupPlayer:
    player_uuid: str
    position: PlayerPosition
    starting_probability: float
    availability_probability: float
    strength: float


@dataclass(frozen=True)
class ExpectedLineup:
    formation: str
    starters: tuple[ExpectedLineupPlayer, ...]
    substitutes: tuple[ExpectedLineupPlayer, ...]
    confidence: float


@dataclass(frozen=True)
class PlayerTeamFeatures:
    candidate_squad_size: int
    player_history_coverage: float
    availability_report_coverage: float
    expected_xi_strength: float
    expected_xi_availability: float
    missing_player_impact: float
    replacement_dropoff: float
    bench_strength: float
    lineup_stability: float
    expected_lineup_confidence: float
    known_absence_count: int
    suspension_count: int
    transfer_uncertainty: float


PLAYER_TEAM_FEATURE_NAMES = tuple(field.name for field in fields(PlayerTeamFeatures))
PLAYER_FEATURE_COLUMNS = tuple(
    f"{side}_{name}" for side in ("home", "away") for name in PLAYER_TEAM_FEATURE_NAMES
)
PLAYER_IDENTITY_COLUMNS = IDENTITY_COLUMNS + (
    "player_feature_contract_version",
    "latest_player_input_available_after",
)
PLAYER_EXPORT_COLUMNS = (
    PLAYER_IDENTITY_COLUMNS + PREMATCH_FEATURE_COLUMNS + PLAYER_FEATURE_COLUMNS + TARGET_COLUMNS
)


@dataclass(frozen=True)
class PlayerEnhancedFeatureRow:
    base: dict[str, str]
    latest_player_input_available_after: datetime | None
    home: PlayerTeamFeatures
    away: PlayerTeamFeatures
    home_lineup: ExpectedLineup
    away_lineup: ExpectedLineup

    def as_flat_dict(self) -> dict[str, Any]:
        output: dict[str, Any] = {
            column: self.base[column]
            for column in IDENTITY_COLUMNS + PREMATCH_FEATURE_COLUMNS + TARGET_COLUMNS
        }
        output["player_feature_contract_version"] = PLAYER_FEATURE_CONTRACT_VERSION
        output["latest_player_input_available_after"] = (
            self.latest_player_input_available_after.isoformat()
            if self.latest_player_input_available_after is not None
            else ""
        )
        output.update({f"home_{key}": value for key, value in asdict(self.home).items()})
        output.update({f"away_{key}": value for key, value in asdict(self.away).items()})
        return output


@dataclass(frozen=True)
class PlayerEnhancedFeatureDataset:
    rows: tuple[PlayerEnhancedFeatureRow, ...]
    base_feature_checksum: str
    player_context_checksum: str
    seasons: tuple[str, ...]


def _weighted_average(values: list[tuple[float, float]], default: float) -> float:
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return default
    return sum(value * weight for value, weight in values) / total_weight


def _profile(
    *,
    player_uuid: str,
    club_uuid: str,
    histories: dict[tuple[str, str], list[PlayerPerformance]],
    global_histories: dict[str, list[PlayerPerformance]],
    availability: AvailabilityObservation | None,
    transferred_recently: bool,
) -> PlayerProfile | None:
    club_history = histories.get((club_uuid, player_uuid), [])[-10:]
    history = club_history or global_histories.get(player_uuid, [])[-10:]
    if not history:
        return None
    recency_weights = [0.85 ** (len(history) - index - 1) for index in range(len(history))]
    start_values = [
        (0.7 * float(item.started) + 0.3 * min(1.0, item.minutes / 90), weight)
        for item, weight in zip(history, recency_weights, strict=True)
    ]
    starting_probability = _weighted_average(start_values, 0.0)
    rating_values = [
        (item.rating, weight)
        for item, weight in zip(history, recency_weights, strict=True)
        if item.rating is not None
    ]
    mean_rating = _weighted_average(
        [(float(value), weight) for value, weight in rating_values], 6.5
    )
    minutes = sum(item.minutes for item in history)
    goals_per_90 = 90 * sum(item.goals for item in history) / max(90, minutes)
    assists_per_90 = 90 * sum(item.assists for item in history) / max(90, minutes)
    reliability = min(1.0, minutes / 900)
    if not club_history:
        reliability *= 0.6
    strength = reliability * (
        (mean_rating - 6.5) / 1.5 + 0.35 * goals_per_90 + 0.25 * assists_per_90
    )
    latest_position = history[-1].position
    return PlayerProfile(
        player_uuid=player_uuid,
        position=latest_position,
        appearances=len(history),
        starting_probability=starting_probability,
        strength=strength,
        strength_confidence=reliability,
        availability_status=availability.status if availability else "unknown",
        availability_probability=(
            availability.availability_probability
            if availability is not None
            else UNKNOWN_AVAILABILITY_PROBABILITY
        ),
        availability_known=availability is not None,
        transferred_recently=transferred_recently,
    )


def _select_profiles(
    profiles: list[PlayerProfile], *, use_availability: bool
) -> list[PlayerProfile]:
    selected: list[PlayerProfile] = []
    for position, required in FORMATION_REQUIREMENTS.items():
        candidates = [profile for profile in profiles if profile.position == position]
        candidates.sort(
            key=lambda item: (
                item.selection_score if use_availability else item.starting_probability,
                item.strength,
                item.player_uuid,
            ),
            reverse=True,
        )
        selected.extend(candidates[:required])
    selected_ids = {item.player_uuid for item in selected}
    remaining = [item for item in profiles if item.player_uuid not in selected_ids]
    remaining.sort(
        key=lambda item: (
            item.selection_score if use_availability else item.starting_probability,
            item.strength,
            item.player_uuid,
        ),
        reverse=True,
    )
    selected.extend(remaining[: max(0, 11 - len(selected))])
    return selected[:11]


def _lineup(profiles: list[PlayerProfile]) -> ExpectedLineup:
    selected = _select_profiles(profiles, use_availability=True)
    selected_ids = {item.player_uuid for item in selected}
    bench_profiles = [item for item in profiles if item.player_uuid not in selected_ids]
    bench_profiles.sort(
        key=lambda item: (item.selection_score, item.strength, item.player_uuid), reverse=True
    )
    substitutes = bench_profiles[:7]
    completeness = len(selected) / 11
    evidence = sum(
        item.strength_confidence * (1.0 if item.availability_known else 0.6) for item in selected
    ) / max(1, len(selected))

    def convert(item: PlayerProfile) -> ExpectedLineupPlayer:
        return ExpectedLineupPlayer(
            player_uuid=item.player_uuid,
            position=item.position,
            starting_probability=item.starting_probability,
            availability_probability=item.availability_probability,
            strength=item.strength,
        )

    return ExpectedLineup(
        formation="4-3-3",
        starters=tuple(convert(item) for item in selected),
        substitutes=tuple(convert(item) for item in substitutes),
        confidence=completeness * evidence,
    )


class PlayerFeatureState:
    """Advance player observations strictly before successive feature cutoffs."""

    def __init__(self, context: PlayerContextDataset) -> None:
        self._context = context
        self._performance_index = 0
        self._transfer_index = 0
        self._histories: dict[tuple[str, str], list[PlayerPerformance]] = {}
        self._global_histories: dict[str, list[PlayerPerformance]] = {}
        self._latest_transfer: dict[str, TransferObservation] = {}
        self.latest_applied_at: datetime | None = None
        self._availability_by_fixture_club: dict[
            tuple[str, str], list[AvailabilityObservation]
        ] = {}
        for observation in context.availability:
            self._availability_by_fixture_club.setdefault(
                (observation.target_match_uuid, observation.club_uuid), []
            ).append(observation)

    def advance(self, cutoff: datetime) -> None:
        while (
            self._performance_index < len(self._context.performances)
            and self._context.performances[self._performance_index].available_after < cutoff
        ):
            item = self._context.performances[self._performance_index]
            self._histories.setdefault((item.club_uuid, item.player_uuid), []).append(item)
            self._global_histories.setdefault(item.player_uuid, []).append(item)
            self.latest_applied_at = (
                item.available_after
                if self.latest_applied_at is None
                else max(self.latest_applied_at, item.available_after)
            )
            self._performance_index += 1
        while (
            self._transfer_index < len(self._context.transfers)
            and self._context.transfers[self._transfer_index].observed_at < cutoff
        ):
            transfer = self._context.transfers[self._transfer_index]
            if transfer.transfer_date <= cutoff.date():
                self._latest_transfer[transfer.player_uuid] = transfer
                self.latest_applied_at = (
                    transfer.observed_at
                    if self.latest_applied_at is None
                    else max(self.latest_applied_at, transfer.observed_at)
                )
            self._transfer_index += 1

    def team_features(
        self,
        *,
        match_uuid: str,
        club_uuid: str,
        kickoff: datetime,
        cutoff: datetime,
    ) -> tuple[PlayerTeamFeatures, ExpectedLineup, datetime | None]:
        availability_items = self._availability_by_fixture_club.get((match_uuid, club_uuid), [])
        latest_availability: dict[str, AvailabilityObservation] = {}
        latest_used = self.latest_applied_at
        for item in availability_items:
            if item.observed_at < cutoff:
                current = latest_availability.get(item.player_uuid)
                if current is None or item.observed_at > current.observed_at:
                    latest_availability[item.player_uuid] = item
                latest_used = (
                    item.observed_at if latest_used is None else max(latest_used, item.observed_at)
                )

        recent_threshold = kickoff - RECENT_SQUAD_WINDOW
        candidate_ids = {
            player_uuid
            for (history_club, player_uuid), history in self._histories.items()
            if history_club == club_uuid and history[-1].kickoff_at >= recent_threshold
        }
        for player_uuid, transfer in self._latest_transfer.items():
            if transfer.from_club_uuid == club_uuid and transfer.to_club_uuid != club_uuid:
                candidate_ids.discard(player_uuid)
            if transfer.to_club_uuid == club_uuid:
                candidate_ids.add(player_uuid)

        profiles: list[PlayerProfile] = []
        for player_uuid in sorted(candidate_ids):
            latest_transfer = self._latest_transfer.get(player_uuid)
            transferred_recently = bool(
                latest_transfer
                and latest_transfer.to_club_uuid == club_uuid
                and kickoff.date() - latest_transfer.transfer_date < TRANSFER_UNCERTAINTY_WINDOW
            )
            profile = _profile(
                player_uuid=player_uuid,
                club_uuid=club_uuid,
                histories=self._histories,
                global_histories=self._global_histories,
                availability=latest_availability.get(player_uuid),
                transferred_recently=transferred_recently,
            )
            if profile is not None:
                profiles.append(profile)

        expected = _lineup(profiles)
        nominal_starters = _select_profiles(profiles, use_availability=False)
        expected_ids = {item.player_uuid for item in expected.starters}
        bench_profiles = [item for item in profiles if item.player_uuid not in expected_ids]
        expected_strength = (
            sum(item.strength * item.availability_probability for item in expected.starters) / 11
        )
        expected_availability = (
            sum(item.availability_probability for item in expected.starters) / 11
        )
        missing_impact = sum(
            max(0.0, item.strength)
            * item.starting_probability
            * (1 - item.availability_probability)
            for item in nominal_starters
        )
        replacement_dropoff = 0.0
        for nominal in nominal_starters:
            replacements = [
                item
                for item in profiles
                if item.player_uuid not in {starter.player_uuid for starter in nominal_starters}
                and item.position == nominal.position
            ]
            best_replacement = max((item.strength for item in replacements), default=0.0)
            replacement_dropoff += max(0.0, nominal.strength - best_replacement) * (
                1 - nominal.availability_probability
            )
        bench_strength = (
            sum(
                item.strength * item.availability_probability
                for item in sorted(
                    bench_profiles,
                    key=lambda item: (item.selection_score, item.strength),
                    reverse=True,
                )[:7]
            )
            / 7
        )
        considered = sorted(
            profiles,
            key=lambda item: (item.starting_probability, item.strength),
            reverse=True,
        )[:18]
        history_coverage = sum(min(1.0, item.appearances / 5) for item in considered) / 18
        availability_coverage = sum(item.availability_known for item in considered) / 18
        known_absences = sum(
            item.availability_status in ("out", "suspended") and item.starting_probability >= 0.35
            for item in profiles
        )
        suspensions = sum(
            item.availability_status == "suspended" and item.starting_probability >= 0.35
            for item in profiles
        )
        lineup_stability = sum(item.starting_probability for item in expected.starters) / 11
        transfer_uncertainty = sum(item.transferred_recently for item in considered) / 18
        features = PlayerTeamFeatures(
            candidate_squad_size=len(profiles),
            player_history_coverage=history_coverage,
            availability_report_coverage=availability_coverage,
            expected_xi_strength=expected_strength,
            expected_xi_availability=expected_availability,
            missing_player_impact=missing_impact,
            replacement_dropoff=replacement_dropoff / 11,
            bench_strength=bench_strength,
            lineup_stability=lineup_stability,
            expected_lineup_confidence=expected.confidence,
            known_absence_count=known_absences,
            suspension_count=suspensions,
            transfer_uncertainty=transfer_uncertainty,
        )
        return features, expected, latest_used


def _parse_aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Phase 8 feature timestamps must be timezone-aware")
    return parsed


def build_player_enhanced_features(
    base_feature_path: Path,
    context: PlayerContextDataset,
) -> PlayerEnhancedFeatureDataset:
    """Augment every Phase 8 row without allowing player-data leakage."""

    validated = validate_feature_export(base_feature_path)
    with base_feature_path.open("r", encoding="utf-8", newline="") as stream:
        base_rows = list(csv.DictReader(stream))
    state = PlayerFeatureState(context)
    output: list[PlayerEnhancedFeatureRow] = []
    for row in base_rows:
        cutoff = _parse_aware(row["feature_cutoff_at"])
        kickoff = _parse_aware(row["kickoff_at"])
        state.advance(cutoff)
        home, home_lineup, home_latest = state.team_features(
            match_uuid=row["match_uuid"],
            club_uuid=row["home_club_uuid"],
            kickoff=kickoff,
            cutoff=cutoff,
        )
        away, away_lineup, away_latest = state.team_features(
            match_uuid=row["match_uuid"],
            club_uuid=row["away_club_uuid"],
            kickoff=kickoff,
            cutoff=cutoff,
        )
        latest_values = [value for value in (home_latest, away_latest) if value is not None]
        latest = max(latest_values) if latest_values else None
        if latest is not None and latest >= cutoff:
            raise ValueError("player input violates the feature cutoff")
        output.append(
            PlayerEnhancedFeatureRow(
                base=row,
                latest_player_input_available_after=latest,
                home=home,
                away=away,
                home_lineup=home_lineup,
                away_lineup=away_lineup,
            )
        )
    return PlayerEnhancedFeatureDataset(
        rows=tuple(output),
        base_feature_checksum=validated.checksum,
        player_context_checksum=context.checksum,
        seasons=validated.seasons,
    )
