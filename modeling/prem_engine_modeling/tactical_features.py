"""Leakage-safe formation and measurable style-proxy features for Phase 15."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from prem_engine_modeling.data import load_historical_dataset
from prem_engine_modeling.features import PREMATCH_FEATURE_COLUMNS, TARGET_COLUMNS
from prem_engine_modeling.player_data import PlayerContextDataset
from prem_engine_modeling.player_features import (
    PLAYER_FEATURE_COLUMNS,
    PLAYER_IDENTITY_COLUMNS,
)

TACTICAL_FEATURE_CONTRACT_VERSION = "tactical-proxy-features-v1"
RECENT_MATCH_COUNT = 5


@dataclass(frozen=True)
class TeamStyleObservation:
    match_uuid: str
    club_uuid: str
    available_after: datetime
    shots_for: int
    shots_against: int
    shots_on_target_for: int
    shots_on_target_against: int
    corners_for: int
    corners_against: int
    fouls: int


@dataclass(frozen=True)
class ShapeObservation:
    match_uuid: str
    club_uuid: str
    available_after: datetime
    defenders: int
    midfielders: int
    attackers: int
    starters: frozenset[str]

    @property
    def label(self) -> str:
        return f"{self.defenders}-{self.midfielders}-{self.attackers}"


@dataclass(frozen=True)
class TacticalTeamFeatures:
    style_sample_count: int
    style_history_coverage: float
    shots_for_per_match: float
    shots_against_per_match: float
    shots_on_target_against_per_match: float
    shot_share: float
    shot_accuracy: float
    corners_for_per_match: float
    corner_share: float
    fouls_per_match: float
    shape_sample_count: int
    shape_history_coverage: float
    expected_defenders: float
    expected_midfielders: float
    expected_attackers: float
    shape_stability: float
    starter_continuity: float


TACTICAL_TEAM_FEATURE_NAMES = tuple(field.name for field in fields(TacticalTeamFeatures))
TACTICAL_FEATURE_COLUMNS = tuple(
    f"{side}_{name}" for side in ("home", "away") for name in TACTICAL_TEAM_FEATURE_NAMES
)
TACTICAL_IDENTITY_COLUMNS = PLAYER_IDENTITY_COLUMNS + (
    "tactical_feature_contract_version",
    "latest_tactical_input_available_after",
)
TACTICAL_EXPORT_COLUMNS = (
    TACTICAL_IDENTITY_COLUMNS
    + PREMATCH_FEATURE_COLUMNS
    + PLAYER_FEATURE_COLUMNS
    + TACTICAL_FEATURE_COLUMNS
    + TARGET_COLUMNS
)


@dataclass(frozen=True)
class TacticalFeatureRow:
    player_row: dict[str, str]
    latest_tactical_input_available_after: datetime | None
    home: TacticalTeamFeatures
    away: TacticalTeamFeatures

    def as_flat_dict(self) -> dict[str, Any]:
        output = {
            column: self.player_row[column]
            for column in PLAYER_IDENTITY_COLUMNS
            + PREMATCH_FEATURE_COLUMNS
            + PLAYER_FEATURE_COLUMNS
            + TARGET_COLUMNS
        }
        output["tactical_feature_contract_version"] = TACTICAL_FEATURE_CONTRACT_VERSION
        output["latest_tactical_input_available_after"] = (
            self.latest_tactical_input_available_after.isoformat()
            if self.latest_tactical_input_available_after is not None
            else ""
        )
        output.update({f"home_{key}": value for key, value in asdict(self.home).items()})
        output.update({f"away_{key}": value for key, value in asdict(self.away).items()})
        return output


@dataclass(frozen=True)
class TacticalFeatureDataset:
    rows: tuple[TacticalFeatureRow, ...]
    player_feature_checksum: str
    historical_match_checksum: str
    player_context_checksum: str
    shape_observation_count: int
    statistic_anomaly_count: int
    seasons: tuple[str, ...]


def _nonnegative(row: dict[str, str], column: str, row_number: int) -> int:
    try:
        value = int(row[column])
    except (KeyError, ValueError) as error:
        raise ValueError(
            f"row {row_number}: missing or invalid tactical statistic {column}"
        ) from error
    if value < 0:
        raise ValueError(f"row {row_number}: tactical statistic {column} is negative")
    return value


def load_style_observations(
    path: Path,
) -> tuple[tuple[TeamStyleObservation, ...], str, int]:
    """Load only auditable post-match counts used as style proxies."""

    historical = load_historical_dataset(path)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    records = {record.match_uuid: record for record in historical.records}
    output: list[TeamStyleObservation] = []
    anomaly_count = 0
    for row_number, row in enumerate(rows, 2):
        record = records[row["match_uuid"]]
        hs = _nonnegative(row, "HS", row_number)
        away_shots = _nonnegative(row, "AS", row_number)
        hst = _nonnegative(row, "HST", row_number)
        ast = _nonnegative(row, "AST", row_number)
        hc = _nonnegative(row, "HC", row_number)
        ac = _nonnegative(row, "AC", row_number)
        hf = _nonnegative(row, "HF", row_number)
        af = _nonnegative(row, "AF", row_number)
        if hst > hs or ast > away_shots:
            anomaly_count += 1
            hst = min(hst, hs)
            ast = min(ast, away_shots)
        output.extend(
            (
                TeamStyleObservation(
                    match_uuid=record.match_uuid,
                    available_after=record.available_after,
                    club_uuid=record.home_club_uuid,
                    shots_for=hs,
                    shots_against=away_shots,
                    shots_on_target_for=hst,
                    shots_on_target_against=ast,
                    corners_for=hc,
                    corners_against=ac,
                    fouls=hf,
                ),
                TeamStyleObservation(
                    match_uuid=record.match_uuid,
                    available_after=record.available_after,
                    club_uuid=record.away_club_uuid,
                    shots_for=away_shots,
                    shots_against=hs,
                    shots_on_target_for=ast,
                    shots_on_target_against=hst,
                    corners_for=ac,
                    corners_against=hc,
                    fouls=af,
                ),
            )
        )
    output.sort(key=lambda item: (item.available_after, item.match_uuid, item.club_uuid))
    return tuple(output), historical.checksum, anomaly_count


def observed_shapes(context: PlayerContextDataset) -> tuple[ShapeObservation, ...]:
    """Derive position-group shapes only where a real starting XI is observed."""

    groups: dict[tuple[str, str], list[Any]] = {}
    for performance in context.performances:
        if performance.started is True:
            groups.setdefault((performance.match_uuid, performance.club_uuid), []).append(
                performance
            )
    output: list[ShapeObservation] = []
    for (match_uuid, club_uuid), starters in groups.items():
        if len(starters) != 11 or sum(item.position == "goalkeeper" for item in starters) != 1:
            continue
        defenders = sum(item.position == "defender" for item in starters)
        midfielders = sum(item.position == "midfielder" for item in starters)
        attackers = sum(item.position == "attacker" for item in starters)
        if defenders + midfielders + attackers != 10:
            continue
        output.append(
            ShapeObservation(
                match_uuid=match_uuid,
                club_uuid=club_uuid,
                available_after=max(item.available_after for item in starters),
                defenders=defenders,
                midfielders=midfielders,
                attackers=attackers,
                starters=frozenset(item.player_uuid for item in starters),
            )
        )
    output.sort(key=lambda item: (item.available_after, item.match_uuid, item.club_uuid))
    return tuple(output)


def _mean(items: list[float]) -> float:
    return fmean(items) if items else 0.0


class TacticalFeatureState:
    """Advance match and lineup observations strictly before each T-24 cutoff."""

    def __init__(
        self,
        styles: tuple[TeamStyleObservation, ...],
        shapes: tuple[ShapeObservation, ...],
    ) -> None:
        self._styles = styles
        self._shapes = shapes
        self._style_index = 0
        self._shape_index = 0
        self._style_history: dict[str, list[TeamStyleObservation]] = {}
        self._shape_history: dict[str, list[ShapeObservation]] = {}

    def advance(self, cutoff: datetime) -> None:
        while self._style_index < len(self._styles):
            style_item = self._styles[self._style_index]
            if style_item.available_after >= cutoff:
                break
            self._style_history.setdefault(style_item.club_uuid, []).append(style_item)
            self._style_index += 1
        while self._shape_index < len(self._shapes):
            shape_item = self._shapes[self._shape_index]
            if shape_item.available_after >= cutoff:
                break
            self._shape_history.setdefault(shape_item.club_uuid, []).append(shape_item)
            self._shape_index += 1

    def team_features(self, club_uuid: str) -> tuple[TacticalTeamFeatures, datetime | None]:
        styles = self._style_history.get(club_uuid, [])[-RECENT_MATCH_COUNT:]
        shapes = self._shape_history.get(club_uuid, [])[-RECENT_MATCH_COUNT:]
        shots_for = sum(item.shots_for for item in styles)
        shots_against = sum(item.shots_against for item in styles)
        shots_on_target = sum(item.shots_on_target_for for item in styles)
        corners_for = sum(item.corners_for for item in styles)
        corners_against = sum(item.corners_against for item in styles)
        shape_counts = Counter(item.label for item in shapes)
        continuity = [
            len(previous.starters & current.starters) / 11
            for previous, current in zip(shapes, shapes[1:], strict=False)
        ]
        latest = [item.available_after for item in styles + shapes]
        return (
            TacticalTeamFeatures(
                style_sample_count=len(styles),
                style_history_coverage=len(styles) / RECENT_MATCH_COUNT,
                shots_for_per_match=_mean([float(item.shots_for) for item in styles]),
                shots_against_per_match=_mean([float(item.shots_against) for item in styles]),
                shots_on_target_against_per_match=_mean(
                    [float(item.shots_on_target_against) for item in styles]
                ),
                shot_share=shots_for / max(1, shots_for + shots_against),
                shot_accuracy=shots_on_target / max(1, shots_for),
                corners_for_per_match=_mean([float(item.corners_for) for item in styles]),
                corner_share=corners_for / max(1, corners_for + corners_against),
                fouls_per_match=_mean([float(item.fouls) for item in styles]),
                shape_sample_count=len(shapes),
                shape_history_coverage=len(shapes) / RECENT_MATCH_COUNT,
                expected_defenders=_mean([float(item.defenders) for item in shapes]),
                expected_midfielders=_mean([float(item.midfielders) for item in shapes]),
                expected_attackers=_mean([float(item.attackers) for item in shapes]),
                shape_stability=(max(shape_counts.values()) / len(shapes) if shapes else 0.0),
                starter_continuity=_mean(continuity),
            ),
            max(latest) if latest else None,
        )


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("feature timestamps must include a timezone")
    return parsed


def build_tactical_features(
    player_feature_path: Path,
    historical_match_path: Path,
    context: PlayerContextDataset,
) -> TacticalFeatureDataset:
    """Append prior-only style and observed-shape features to Phase 10 rows."""

    player_body = player_feature_path.read_bytes()
    with player_feature_path.open("r", encoding="utf-8", newline="") as stream:
        player_rows = list(csv.DictReader(stream))
    if not player_rows:
        raise ValueError("player feature export contains no rows")
    styles, historical_checksum, anomaly_count = load_style_observations(historical_match_path)
    shapes = observed_shapes(context)
    state = TacticalFeatureState(styles, shapes)
    output: list[TacticalFeatureRow] = []
    for row in player_rows:
        cutoff = _aware(row["feature_cutoff_at"])
        state.advance(cutoff)
        home, home_latest = state.team_features(row["home_club_uuid"])
        away, away_latest = state.team_features(row["away_club_uuid"])
        latest_values = [value for value in (home_latest, away_latest) if value is not None]
        latest = max(latest_values) if latest_values else None
        if latest is not None and latest >= cutoff:
            raise ValueError("tactical input violates the feature cutoff")
        output.append(
            TacticalFeatureRow(
                player_row=row,
                latest_tactical_input_available_after=latest,
                home=home,
                away=away,
            )
        )
    seasons = tuple(dict.fromkeys(row["season"] for row in player_rows))
    return TacticalFeatureDataset(
        rows=tuple(output),
        player_feature_checksum=hashlib.sha256(player_body).hexdigest(),
        historical_match_checksum=historical_checksum,
        player_context_checksum=context.checksum,
        shape_observation_count=len(shapes),
        statistic_anomaly_count=anomaly_count,
        seasons=seasons,
    )
