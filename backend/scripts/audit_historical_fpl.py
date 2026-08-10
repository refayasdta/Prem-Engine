"""Download and audit public historical FPL player-fixture data without importing it."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from prem_engine_api.config import get_settings
from prem_engine_api.providers.historical_fpl.audit import (
    audit_season,
    parse_csv,
    summarize_audit,
)
from prem_engine_api.providers.historical_fpl.client import HistoricalFplClient
from prem_engine_api.providers.raw_storage import LocalRawResponseStore

DEFAULT_SEASONS = ["2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
DEFAULT_JSON_OUTPUT = Path("data/contracts/fpl-historical/coverage-summary.json")
DEFAULT_MARKDOWN_OUTPUT = Path("data/contracts/fpl-historical/AUDIT_REPORT.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="+", default=DEFAULT_SEASONS)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument(
        "--confirm-public-download",
        action="store_true",
        help="Required acknowledgement that public GitHub files will be downloaded.",
    )
    return parser.parse_args()


def _percentage(value: Any) -> str:
    return f"{float(value) * 100:.1f}%"


def render_markdown(summary: dict[str, Any]) -> str:
    """Render the audit decision in plain language for manual review."""

    gate = summary["training_gate"]
    lines = [
        "# Historical FPL data audit",
        "",
        f"Date: {summary['audit_date']}",
        "",
        "## Result",
        "",
        (
            "The dataset **passes the player-strength source gate**."
            if gate["player_strength_source_ready"]
            else "The dataset **does not yet pass the player-strength source gate**."
        ),
        "",
        "It does not by itself complete the historical injury or confirmed-lineup model.",
        "",
        (
            "| Season | Available | Fixtures | Player performances | "
            "Candidate coverage | Starts field |"
        ),
        "|---|---:|---:|---:|---:|---:|",
    ]
    for season in summary["seasons"]:
        if not season.get("available"):
            lines.append(f"| {season['season']} | No | 0 | 0 | 0.0% | No |")
            continue
        lines.append(
            "| {season} | Yes | {fixtures:,} | {performances:,} | {coverage} | {starts} |".format(
                season=season["season"],
                fixtures=season["fixture_count"],
                performances=season["unique_player_fixture_performance_count"],
                coverage=_percentage(season["candidate_covered_fixture_rate"]),
                starts="Yes" if season["start_indicator_available"] else "No",
            )
        )
    lines.extend(
        [
            "",
            "## Training gate",
            "",
            f"- Unique player-match performances: {gate['performance_record_count']:,} "
            f"(minimum {gate['minimum_performance_records']:,}).",
            f"- Candidate-covered fixtures: {gate['candidate_covered_fixture_count']:,} of "
            f"{gate['target_fixture_count']:,} ({_percentage(gate['candidate_coverage_rate'])}; "
            f"minimum {_percentage(gate['minimum_candidate_coverage_rate'])}).",
            (
                "- Player identity mapping adequate: "
                f"{str(gate['identity_mapping_adequate']).lower()}."
            ),
            f"- Player-strength source ready: {str(gate['player_strength_source_ready']).lower()}.",
            (
                "- Full availability model ready: "
                f"{str(gate['full_availability_model_ready']).lower()}."
            ),
            "",
            "## Safe use",
            "",
            "- Match outcomes and player performance fields become usable only after that match.",
            "- Same-gameweek `xP`, transfer, popularity, and value fields are excluded from "
            "same-fixture features because their observation time is uncertain.",
            "- Missing injury information means unknown, never available.",
            (
                "- Player IDs remain external references and must map to internal "
                "`player_uuid` values."
            ),
            "",
            "## Remaining limitations",
            "",
            f"- {gate['full_availability_blocker']}",
            "- Provider ratings are not expected in FPL records and remain optional.",
            "- Repository and upstream data terms must be reviewed before public redistribution.",
            "- No data was imported and no model was trained during this audit.",
            "",
        ]
    )
    return "\n".join(lines)


async def run_audit(args: argparse.Namespace) -> None:
    if not args.confirm_public_download:
        raise SystemExit(
            "Public download not confirmed; no files were requested. "
            "Re-run with --confirm-public-download after approval."
        )
    settings = get_settings()
    maximum_downloads = len(args.seasons) * 3
    season_results: list[dict[str, Any]] = []
    async with HistoricalFplClient(
        settings=settings,
        raw_store=LocalRawResponseStore(settings.raw_data_root),
        max_downloads=maximum_downloads,
    ) as client:
        for season in args.seasons:
            merged = await client.get_csv(f"/{season}/gws/merged_gw.csv")
            if merged.status_code != 200:
                season_results.append(
                    {
                        "season": season,
                        "available": False,
                        "status_code": merged.status_code,
                        "merged_checksum": merged.raw_checksum,
                    }
                )
                continue
            players = await client.get_csv(f"/{season}/players_raw.csv")
            fixtures = await client.get_csv(f"/{season}/fixtures.csv")
            if players.status_code != 200 or fixtures.status_code != 200:
                season_results.append(
                    {
                        "season": season,
                        "available": False,
                        "status_code": {
                            "merged": merged.status_code,
                            "players": players.status_code,
                            "fixtures": fixtures.status_code,
                        },
                        "checksums": {
                            "merged": merged.raw_checksum,
                            "players": players.raw_checksum,
                            "fixtures": fixtures.raw_checksum,
                        },
                    }
                )
                continue
            result = audit_season(
                season=season,
                merged=parse_csv(merged.body),
                players=parse_csv(players.body),
                fixtures=parse_csv(fixtures.body),
            )
            result["source_checksums"] = {
                "merged": merged.raw_checksum,
                "players": players.raw_checksum,
                "fixtures": fixtures.raw_checksum,
            }
            season_results.append(result)

        summary = {
            "contract_version": "historical-fpl-coverage-audit-v1",
            "audit_date": "2026-08-10",
            "sanitized": True,
            "source": "vaastav/Fantasy-Premier-League",
            "download_count": client.download_count,
            "maximum_download_count": maximum_downloads,
            "raw_responses_stored_locally": True,
            "seasons": season_results,
            "training_gate": summarize_audit(
                season_results, target_fixture_count=len(args.seasons) * 380
            ),
            "training_started": False,
            "data_imported": False,
        }

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(summary), encoding="utf-8")
    print(render_markdown(summary))
    print(f"Downloads consumed: {summary['download_count']} of {maximum_downloads} allowed")
    print("No data was imported and training was not started.")


def main() -> None:
    asyncio.run(run_audit(parse_args()))


if __name__ == "__main__":
    main()
