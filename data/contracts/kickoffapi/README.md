# KickoffAPI Contracts

Provider contracts are generated from controlled read-only probes. Generated
summaries contain response shapes and rate-limit metadata only; they must never
contain the API key, authorization headers, raw player data, or full response
values.

Run from the repository root after setting `KICKOFF_API_KEY` locally:

```powershell
python backend/scripts/probe_kickoffapi.py
```

The Phase 4 probe is capped at three v2 requests. Every request first reserves
one slot in the PostgreSQL daily budget, writes an audit-ledger row, and stores
the byte-exact compressed response under ignored `data/raw/`. The generated
sanitized `probe-summary.json` should be reviewed before it is committed.

The adapter deliberately accepts both v2 shapes currently shown by the official
documentation: native prefixed identifiers with `{data, meta}` and league-code
identifiers with `{data, count, page, totalPages}`. This protects ingestion from
the documented migration variant even though the live account returned the
first form.

The 2026-08-07 authenticated probe returned `{data, meta}` with cursor pagination
for leagues, teams, and fixtures. All three byte-exact captures passed the DTO
validators. `probe-summary.json` contains structural types and quota metadata,
not provider values or credentials.

Phase 10 adds `player-coverage-summary.json`, produced by a bounded seven-request
audit. Player profiles, a squad, and injuries were present. The sampled historical
fixture returned 404 for lineups and fixture-player statistics, while the sampled
team transfer response was empty. The live injury response was revalidated offline
after adapting the tolerant DTO to its observed nested shape.

The account dashboard confirms a 100-request daily limit and a separate
30-request-per-minute limit. During this audit, `X-RateLimit-Limit: 30` described
the minute window; the accompanying remaining count fell from 29 to 23. The raw
header values remain in the sanitized summaries as evidence. Prem Engine enforces
its configured daily budget separately and also blocks when the active provider
window reports no remaining requests before its reset time.
