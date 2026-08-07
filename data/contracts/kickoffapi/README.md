# KickoffAPI Contracts

Provider contracts are generated from controlled read-only probes. Generated
summaries contain response shapes and rate-limit metadata only; they must never
contain the API key, authorization headers, raw player data, or full response
values.

Run from the repository root after setting `KICKOFF_API_KEY` locally:

```powershell
python backend/scripts/probe_kickoffapi.py
```

The Phase 2 probe is capped at four requests. The generated
`probe-summary.json` should be reviewed before it is committed.
