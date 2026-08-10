"""Verified local access to immutable historical FPL audit captures."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from prem_engine_api.providers.historical_fpl.audit import ParsedCsv, parse_csv


class HistoricalFplArchiveError(ValueError):
    """Raised when the audited manifest and immutable captures disagree."""


@dataclass(frozen=True)
class ArchivedCsv:
    kind: str
    season: str
    checksum: str
    object_key: str
    retrieved_at: datetime
    source_url: str
    parsed: ParsedCsv


@dataclass(frozen=True)
class ArchivedSeason:
    season: str
    merged: ArchivedCsv
    players: ArchivedCsv
    fixtures: ArchivedCsv
    stable_player_code_column: str
    start_indicator_available: bool


def _retrieved_at(path: Path) -> datetime:
    try:
        date_parts = path.parts[-4:-1]
        stamp = path.name.split("_", 1)[0]
        parsed = datetime.strptime("".join(date_parts) + stamp, "%Y%m%d%H%M%S%f")
        return parsed.replace(tzinfo=UTC)
    except (ValueError, IndexError) as error:
        raise HistoricalFplArchiveError(f"unrecognized raw capture path: {path}") from error


class HistoricalFplArchive:
    """Read only captures listed by the sanitized coverage manifest."""

    def __init__(self, *, manifest_path: Path, raw_root: Path, base_url: str) -> None:
        self._manifest_path = manifest_path
        self._raw_root = raw_root
        self._base_url = base_url.rstrip("/")

    def _manifest(self) -> dict[str, Any]:
        try:
            document = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HistoricalFplArchiveError("cannot read historical FPL manifest") from error
        if document.get("contract_version") != "historical-fpl-coverage-audit-v1":
            raise HistoricalFplArchiveError("unsupported historical FPL manifest version")
        if not document.get("sanitized") or not document.get("raw_responses_stored_locally"):
            raise HistoricalFplArchiveError("manifest does not certify immutable local captures")
        return cast(dict[str, Any], document)

    def _capture(self, *, season: str, kind: str, checksum: str) -> ArchivedCsv:
        matches = list(self._raw_root.rglob(f"*_{checksum[:12]}.csv.gz"))
        if len(matches) != 1:
            raise HistoricalFplArchiveError(
                f"expected one {season} {kind} capture for {checksum}, found {len(matches)}"
            )
        path = matches[0]
        try:
            body = gzip.decompress(path.read_bytes())
        except (OSError, gzip.BadGzipFile) as error:
            raise HistoricalFplArchiveError(f"cannot decompress {path}") from error
        if hashlib.sha256(body).hexdigest() != checksum:
            raise HistoricalFplArchiveError(f"checksum mismatch for {path}")
        suffix = {
            "merged": "gws/merged_gw.csv",
            "players": "players_raw.csv",
            "fixtures": "fixtures.csv",
        }[kind]
        return ArchivedCsv(
            kind=kind,
            season=season,
            checksum=checksum,
            object_key=path.relative_to(self._raw_root.parent).as_posix(),
            retrieved_at=_retrieved_at(path),
            source_url=f"{self._base_url}/{season}/{suffix}",
            parsed=parse_csv(body),
        )

    def seasons(self) -> tuple[ArchivedSeason, ...]:
        manifest = self._manifest()
        output: list[ArchivedSeason] = []
        for record in manifest.get("seasons", []):
            if not record.get("available"):
                continue
            season = str(record["season"])
            checksums = record["source_checksums"]
            stable_column = str(record.get("stable_player_code_column") or "")
            if stable_column not in ("code", "opta_code"):
                raise HistoricalFplArchiveError(f"{season} has no reviewed stable player code")
            output.append(
                ArchivedSeason(
                    season=season,
                    merged=self._capture(
                        season=season, kind="merged", checksum=str(checksums["merged"])
                    ),
                    players=self._capture(
                        season=season, kind="players", checksum=str(checksums["players"])
                    ),
                    fixtures=self._capture(
                        season=season, kind="fixtures", checksum=str(checksums["fixtures"])
                    ),
                    stable_player_code_column=stable_column,
                    start_indicator_available=bool(record.get("start_indicator_available")),
                )
            )
        if not output:
            raise HistoricalFplArchiveError("manifest contains no importable seasons")
        return tuple(output)
