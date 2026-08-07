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
