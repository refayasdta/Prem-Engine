# API-Football coverage audit

API-Football is being evaluated as a secondary historical player-data source. It
does not replace canonical `match_uuid`, `club_uuid`, or `player_uuid` values and
does not replace KickoffAPI for current fixture synchronization.

The audit checks Premier League seasons 2020 through 2025 for declared and
observed lineup and per-fixture player-statistics coverage. It makes at most four
requests per season: league coverage, one completed fixture, its lineup, and its
player statistics. The default six-season audit is therefore capped at 24 calls.

Raw byte-exact responses are compressed under ignored `data/raw/apifootball/`.
The generated `coverage-summary.json` contains structural types, counts, public
coverage flags, quota metadata, and checksums only. It must never contain the API
key, request headers, player names, provider IDs, or full response values.

The command refuses to make a request unless the key is configured and the live
audit is explicitly confirmed:

```powershell
.\scripts\probe-api-football-coverage.ps1 -ConfirmLiveAudit
```

This audit does not import data or train a model. A production adapter, canonical
identity mapping, historical import, cutoff validation, and training-gate review
remain separate approved work if the source passes coverage validation.

## 2026-08-10 result

The approved audit made 23 of its 24 allowed requests and then stopped. The free
plan exposes seasons 2022, 2023, and 2024, while provider plan responses deny
2020, 2021, and 2025. The initial use of the paid-only `last` query parameter was
removed before the accessible-season samples were repeated.

For both 2022 and 2023, API-Football returned 380 finished fixtures. One sampled
match per season returned two team lineups with 22 starters and 18 substitutes,
plus two team player-statistic groups containing 40 player records. The 2024
season declares the same coverage and returned 380 fixtures, but its dependent
sample reached the provider's minute window after the preceding calls.

The result proves that API-Football can supply the missing lineup and player-match
record shapes for accessible Premier League seasons. The free plan cannot fill
the complete six-season training window; access to the blocked seasons must be
verified on a paid plan before historical import begins.
