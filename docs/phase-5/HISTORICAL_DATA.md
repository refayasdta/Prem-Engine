# Phase 5 Historical Data

Date: 2026-08-07

## Outcome

Phase 5 imports six complete Premier League seasons from Football-Data.co.uk:
2020/21 through 2025/26. Each season contains 380 validated matches, producing
2,280 canonical matches and accepted results for baseline model development.

All 2,280 rows include exact kickoff times and the core home/away statistics for
shots, shots on target, corners, fouls, yellow cards, and red cards. Coverage is
recorded in `data/contracts/football-data/coverage-summary.json`.

## Source and usage policy

Football-Data describes the files as free data for match prediction and
quantitative testing. Its public notes define the CSV fields and acknowledge the
upstream sources, but do not grant a broad redistribution license. Prem Engine
therefore:

- keeps byte-exact compressed CSVs private under ignored `data/raw/`;
- records URLs, retrieval times, SHA-256 checksums, and schema fingerprints;
- commits only mappings, code, documentation, and sanitized coverage evidence;
- does not expose source CSVs or derived bulk datasets as website downloads;
- retains betting odds only for offline benchmark comparison.

Official references:

- <https://www.football-data.co.uk/data>
- <https://www.football-data.co.uk/englandm.php>
- <https://www.football-data.co.uk/notes.txt>

## Import boundary

The pipeline is deliberately provider-specific at its edge:

```text
public E0.csv
  -> size-bounded HTTP download
  -> immutable gzip archive and SHA-256 checksum
  -> strict header, type, range, date, and score/result validation
  -> reviewed club alias resolution
  -> canonical season, club, match, and accepted-result records
  -> leakage-aware modeling and benchmark exports
  -> coverage report
```

CSV parsing accepts UTF-8 with a byte-order mark and Windows-1252. A file is
rejected if it lacks required columns, contains duplicate headers, invalid
dates/times, negative counts, inconsistent result codes, a non-E0 division,
duplicate fixtures, unreviewed clubs, or dates outside the requested season.

## Identity and correction handling

`match_uuid` remains the canonical match identity. Football-Data has no fixture
identifier in these files, so the adapter creates a deterministic external key
from competition, season, date, home alias, and away alias. A source key can map
to only one internal match.

Club names never use fuzzy matching. The committed
`data/mappings/football-data-clubs.csv` registry is human-reviewed and maps each
source alias to one canonical club. An unknown alias stops the import so it can
be reviewed explicitly.

Reimporting an identical URL/checksum is a no-op. If the source content later
changes, the new CSV is archived as a distinct source version. Stable fixtures
reuse their existing `match_uuid`; changed scores create a new accepted actual
result revision and retain the superseded revision for audit.

## Database additions

The Phase 5 migration adds:

- `kickoff_precision` on `matches`, distinguishing exact and date-only times;
- `historical_source_files`, the immutable source manifest;
- `club_aliases`, the reviewed provider-to-canonical identity bridge;
- `historical_match_records`, source-row provenance, availability timestamps,
  half-time values, match statistics, and isolated benchmark odds.

Source payloads are never placed in PostgreSQL. Only normalized values, object
keys, and cryptographic checksums are stored there.

## Time safety and odds isolation

Each historical record has `available_after`, conservatively set after the
match. Model features may use a record only when:

```text
record.available_after < target.feature_cutoff_at
```

The modeling export labels match statistics as lagged-history-only inputs. The
current match's outcome and statistics are targets/history rows, never features
for that same match.

Odds are written to a separate benchmark export. Football-Data's fields vary
between opening, pre-closing, and closing observations, and the exact observation
time is not present per row. All imported odds therefore carry
`odds_timing=mixed_or_unknown` and `training_eligible=false`.

## Generated local artifacts

These outputs are reproducible but intentionally ignored by Git:

| Artifact | Rows | SHA-256 |
| --- | ---: | --- |
| `historical_training_matches.csv` | 2,280 | `9cee9fad4b81f79a3c665872d7b24de2973d4e4195122813ccb6aabbbfd93929` |
| `historical_benchmark_odds.csv` | 2,280 | `68de14879f546083eacaeb1a089dd7eac10cbc3637b6f2571f8b2b31cd5555d0` |
| `historical_coverage.json` | 2,280 represented matches | `887cf054741c756bdf5f9b9421b83556182f021ad73a50c21bf7d75ade77a068` |

The six compressed raw CSVs occupy approximately 288 KiB. The normalized
training and isolated odds exports occupy approximately 1.63 MiB together.

## Reproducing the import

With PostgreSQL running and `DATABASE_URL` configured:

```powershell
alembic upgrade head
python backend/scripts/import_historical_data.py --from-season 2020 --to-season 2025
```

The command downloads each season sequentially, commits one season per database
transaction, then regenerates the modeling, odds, and coverage artifacts. It
does not consume the KickoffAPI request allowance.
