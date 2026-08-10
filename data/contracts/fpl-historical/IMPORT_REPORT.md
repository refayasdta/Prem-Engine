# Historical FPL player import report

## Result

The audited FPL archive has been attached to the canonical Premier League match
database. The import is complete and repeatable. It did **not** train a model.

| Measure | Result |
| --- | ---: |
| Seasons | 6 |
| Canonical fixtures covered | 2,280 / 2,280 |
| Stable player identities | 2,640 |
| Unique player-match performances | 66,665 |
| Immutable source files registered | 18 |
| Observed starter flags | 45,787 |
| Unknown starter flags | 20,878 |
| Identical duplicate source rows skipped | 6 |
| Performance timestamps before kickoff | 0 |

## What was imported

- Minutes, position, goals, assists, cards, saves, clean sheets, bonus/BPS,
  selected expected-stat fields, and other completed-match performance facts.
- Stable FPL/Opta player codes as external references to internal `player_uuid`
  identities.
- FPL fixture IDs as external references to existing internal `match_uuid`
  identities.
- Full source-file, source-row, checksum, and availability-time provenance.

## What was deliberately excluded

Same-fixture expected points, player popularity, transfers, price, and transfer
balance were not imported into the modeling observations. They may contain
information that was not safely available at the forecast cutoff.

FPL does not preserve reliable 24-hour injury snapshots for these seasons, so
the import does not claim to solve the historical availability-data gap.

The 2020/21 and 2021/22 files do not contain starter flags. Those 20,878 records
remain explicitly `unknown`. Their minutes remain usable as a lower-confidence
lineup signal, but the system never labels them as observed starters or
substitutes.

## Repeatability check

A second complete import registered zero new files, fixtures, players, or
performances. All 66,671 participant source rows were recognized; six are exact
duplicates in the public 2025/26 merged file and map to 66,665 unique canonical
performances.

## Next gate

The next phase is to export the normalized player context, rebuild the
cutoff-safe feature dataset, review its human-readable coverage report, and
only then ask for separate approval to run manual model training.
