# Phase 3 Domain Schema

Date: 2026-08-07

Phase 3 turns the lifecycle policy into a PostgreSQL schema. The first Alembic
migration is `8867eff66966_create_core_domain_schema.py`.

## Identity and football data

- `competitions` and `seasons` define the competition boundary and rules version.
- `clubs`, `players`, `season_clubs`, and `squad_memberships` preserve identities
  independently of a single provider or season.
- Club, player, and match external-reference tables map provider identifiers to
  stable internal UUIDs.
- `matches.match_uuid` is the canonical fixture identity. Provider IDs are never
  used as foreign keys by forecasting or product tables.
- `fixture_schedule_revisions` is append-oriented and allows exactly one current
  schedule revision for each match.
- `actual_result_revisions` allows provider corrections while permitting exactly
  one accepted result at a time.

## Predictions and simulations

- `prediction_versions` records the feature cutoff, model version, probability
  distribution, model-produced expected goals, and lifecycle state.
- A partial unique index permits only one `active_locked` or `evaluated`
  prediction for a match.
- `predicted_lineups` and `stored_simulations` are one-to-one children of a
  prediction version. Voiding a prediction retains both artifacts for audit.
- PostgreSQL triggers prevent updates to locked prediction payloads and prevent
  updates or deletion of their lineup and simulation artifacts.

## Separate standings

`standings_snapshots.kind` distinguishes `real`, `simulated`, and
`fair_comparison` tables. Rows validate that wins, draws, and losses add up to
matches played. Each snapshot has one row and one position per club.

## Operations and audit

- `raw_fetches` stores append-only retrieval metadata, checksums, schema versions,
  and private object-storage keys rather than overwriting provider responses.
- `provider_request_budgets` supports an atomic daily request reservation. The
  KickoffAPI operational limit defaults to 85, retaining 15 of the account's 100
  daily requests as a safety margin.
- `job_runs` provides unique idempotency keys, due times, attempts, and leases.
- `lifecycle_events` records state changes and is protected by an append-only
  database trigger.

## Postponement transaction

The `reschedule_match` service locks the canonical match, supersedes its schedule,
voids any official prediction, schedules a replacement exactly 24 hours before
the new kickoff, and queues simulated-standings recalculation. All changes occur
in one database transaction.

## Local validation

The local container binds PostgreSQL to `127.0.0.1:55432` by default because a
native PostgreSQL service may already own port 5432. CI uses an isolated
PostgreSQL 16 service on its standard port.

```powershell
docker compose up -d postgres
$env:DATABASE_URL = "postgresql+asyncpg://prem_engine:prem_engine@127.0.0.1:55432/prem_engine"
$env:TEST_DATABASE_URL = $env:DATABASE_URL
alembic upgrade head
pytest
```
