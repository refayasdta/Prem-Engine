# T-24 forecast rehearsal

The rehearsal command exercises the production forecast path with a real canonical match and the
checksum-pinned model artifacts. It builds real expected lineups, runs both inference artifacts,
persists an official forecast and stored simulation, reads the public response during the live and
complete phases, and then rolls the database transaction back.

It makes no provider requests and refuses to run when `APP_ENV=production`.

## Prerequisites

- Apply every Alembic migration to a development or staging database.
- Load one upcoming canonical match without an active prediction.
- Load at least 14 eligible canonical players for both clubs, including a goalkeeper and enough
  positional coverage to select 11 starters and at least three substitutes.
- Ensure the configured goal and detailed-statistics artifact files exist and match their configured
  SHA-256 checksums.

## Run

```powershell
python backend/scripts/rehearse_t24_forecast.py --match-uuid <canonical-match-uuid>
```

A successful command exits with status zero and prints evidence similar to:

```json
{
  "status": "passed",
  "rolled_back": true,
  "home_starters": 11,
  "away_starters": 11,
  "live_state": "live",
  "complete_state": "complete",
  "final_score_withheld_while_live": true,
  "final_score_revealed_when_complete": true
}
```

Any missing artifact, checksum mismatch, incomplete lineup, persistence failure, invalid state, or
premature final-score exposure makes the command fail. Because the transaction is always rolled
back, the rehearsal does not publish or retain an official prediction.

## Deployment gate

Run this command successfully against staging before configuring the production scheduler. After the
Cloud Run job and Cloud Scheduler entry exist, perform one additional staging rehearsal through the
real scheduler trigger and confirm its logs, retry behavior, and alert delivery.
