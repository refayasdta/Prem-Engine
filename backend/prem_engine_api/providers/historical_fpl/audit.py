"""Coverage, identity, and leakage audit for historical FPL CSV files."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

REQUIRED_PERFORMANCE_COLUMNS = {
    "element",
    "fixture",
    "kickoff_time",
    "minutes",
    "team",
    "position",
    "goals_scored",
    "assists",
}
POST_MATCH_ONLY_COLUMNS = {
    "assists",
    "bonus",
    "bps",
    "clean_sheets",
    "creativity",
    "expected_assists",
    "expected_goal_involvements",
    "expected_goals",
    "expected_goals_conceded",
    "goals_conceded",
    "goals_scored",
    "ict_index",
    "influence",
    "minutes",
    "penalties_missed",
    "penalties_saved",
    "red_cards",
    "saves",
    "team_a_score",
    "team_h_score",
    "threat",
    "total_points",
    "yellow_cards",
}
POTENTIAL_SAME_FIXTURE_LEAKAGE_COLUMNS = {
    "selected",
    "transfers_balance",
    "transfers_in",
    "transfers_out",
    "value",
    "xP",
}


@dataclass(frozen=True)
class ParsedCsv:
    """CSV header and rows after UTF-8 decoding."""

    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]


def parse_csv(body: bytes) -> ParsedCsv:
    """Parse one public CSV with stable empty-value handling."""

    text = body.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("historical FPL CSV has no header")
    rows = tuple({str(key): value or "" for key, value in row.items()} for row in reader)
    return ParsedCsv(columns=tuple(reader.fieldnames), rows=rows)


def _positive_integer(value: str) -> int | None:
    try:
        parsed = int(float(value))
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def audit_season(
    *, season: str, merged: ParsedCsv, players: ParsedCsv, fixtures: ParsedCsv
) -> dict[str, Any]:
    """Measure whether one season can safely populate player-performance history."""

    merged_columns = set(merged.columns)
    missing_required = sorted(REQUIRED_PERFORMANCE_COLUMNS - merged_columns)
    fixture_ids = {row.get("fixture", "") for row in merged.rows if row.get("fixture")}
    source_fixture_ids = {row.get("id", "") for row in fixtures.rows if row.get("id")}
    player_ids = {row.get("id", "") for row in players.rows if row.get("id")}
    merged_player_ids = {row.get("element", "") for row in merged.rows if row.get("element")}
    mapped_player_ids = merged_player_ids & player_ids

    participant_rows = 0
    unique_performances: set[tuple[str, str]] = set()
    candidate_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    participant_counts: dict[str, int] = defaultdict(int)
    for row in merged.rows:
        fixture_id = row.get("fixture", "")
        player_id = row.get("element", "")
        team = row.get("team", "")
        if fixture_id and team:
            candidate_counts[fixture_id][team] += 1
        minutes = _positive_integer(row.get("minutes", ""))
        if fixture_id and player_id and minutes is not None and minutes > 0:
            participant_rows += 1
            unique_performances.add((fixture_id, player_id))
            participant_counts[fixture_id] += 1

    candidate_covered = sum(
        1
        for teams in candidate_counts.values()
        if len(teams) == 2 and all(count >= 15 for count in teams.values())
    )
    participant_covered = sum(
        1 for fixture_id in fixture_ids if participant_counts.get(fixture_id, 0) >= 22
    )
    stable_code_column = next(
        (column for column in ("opta_code", "code") if column in players.columns), None
    )
    stable_code_count = (
        sum(1 for row in players.rows if row.get(stable_code_column, ""))
        if stable_code_column
        else 0
    )
    fixture_count = len(fixture_ids)
    source_fixture_count = len(source_fixture_ids)
    player_mapping_rate = (
        len(mapped_player_ids) / len(merged_player_ids) if merged_player_ids else 0.0
    )
    fixture_mapping_rate = (
        len(fixture_ids & source_fixture_ids) / len(fixture_ids) if fixture_ids else 0.0
    )

    return {
        "season": season,
        "available": True,
        "merged_row_count": len(merged.rows),
        "unique_player_count": len(merged_player_ids),
        "participant_row_count": participant_rows,
        "unique_player_fixture_performance_count": len(unique_performances),
        "fixture_count": fixture_count,
        "fixture_file_row_count": len(fixtures.rows),
        "fixture_file_unique_count": source_fixture_count,
        "fixture_id_mapping_rate": round(fixture_mapping_rate, 6),
        "candidate_covered_fixture_count": candidate_covered,
        "candidate_covered_fixture_rate": round(
            candidate_covered / fixture_count if fixture_count else 0.0, 6
        ),
        "participant_covered_fixture_count": participant_covered,
        "participant_covered_fixture_rate": round(
            participant_covered / fixture_count if fixture_count else 0.0, 6
        ),
        "player_identity_mapping_rate": round(player_mapping_rate, 6),
        "stable_player_code_column": stable_code_column,
        "stable_player_code_count": stable_code_count,
        "required_columns_missing": missing_required,
        "start_indicator_available": "starts" in merged_columns,
        "rating_available": "rating" in merged_columns,
        "historical_injury_snapshot_available": False,
        "post_match_only_columns_present": sorted(POST_MATCH_ONLY_COLUMNS & merged_columns),
        "potential_same_fixture_leakage_columns_present": sorted(
            POTENTIAL_SAME_FIXTURE_LEAKAGE_COLUMNS & merged_columns
        ),
    }


def summarize_audit(seasons: list[dict[str, Any]], *, target_fixture_count: int) -> dict[str, Any]:
    """Combine season evidence into the Phase 10 training-gate decision."""

    available = [season for season in seasons if season.get("available")]
    performance_count = sum(
        int(season["unique_player_fixture_performance_count"]) for season in available
    )
    fixture_count = sum(int(season["fixture_count"]) for season in available)
    candidate_covered = sum(int(season["candidate_covered_fixture_count"]) for season in available)
    fixture_coverage_rate = fixture_count / target_fixture_count if target_fixture_count else 0.0
    candidate_coverage_rate = (
        candidate_covered / target_fixture_count if target_fixture_count else 0.0
    )
    performance_gate = performance_count >= 10_000
    coverage_gate = candidate_coverage_rate >= 0.7
    required_columns_complete = all(not season["required_columns_missing"] for season in available)
    identity_mapping_adequate = bool(available) and all(
        float(season["player_identity_mapping_rate"]) >= 0.95 for season in available
    )
    return {
        "target_fixture_count": target_fixture_count,
        "available_season_count": len(available),
        "performance_record_count": performance_count,
        "observed_fixture_count": fixture_count,
        "fixture_coverage_rate": round(fixture_coverage_rate, 6),
        "candidate_covered_fixture_count": candidate_covered,
        "candidate_coverage_rate": round(candidate_coverage_rate, 6),
        "minimum_performance_records": 10_000,
        "minimum_candidate_coverage_rate": 0.7,
        "performance_gate_passes": performance_gate,
        "coverage_gate_passes": coverage_gate,
        "required_columns_complete": required_columns_complete,
        "identity_mapping_adequate": identity_mapping_adequate,
        "player_strength_source_ready": (
            performance_gate
            and coverage_gate
            and required_columns_complete
            and identity_mapping_adequate
        ),
        "full_availability_model_ready": False,
        "full_availability_blocker": (
            "Historical FPL rows do not preserve reliable 24-hour injury snapshots or "
            "confirmed starting status across every season."
        ),
    }
