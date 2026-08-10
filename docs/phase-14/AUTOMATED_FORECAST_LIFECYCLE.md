# Phase 14: Automated forecast lifecycle

Phase 14 turns the Phase 13 stored-simulation generator into an automatic,
recoverable T-24 service. Website users do not press a simulate button. A
one-shot worker runs every minute, finds fixtures whose prediction time has
arrived, and publishes one complete immutable forecast for the current schedule
revision.

## End-to-end flow

1. Fixture synchronization stores a resolved canonical `match_uuid`, an exact
   kickoff, and a current schedule revision.
2. The dispatcher creates one `generate_prediction` job for that match revision.
   Its unique idempotency key prevents duplicate work.
3. At or after `kickoff - 24 hours`, a worker claims the row with a PostgreSQL
   lease. `FOR UPDATE SKIP LOCKED` prevents two workers from claiming it.
4. The worker loads the checksum-pinned Phase 7 goal artifact and Phase 12
   detailed-statistics artifact.
5. Current-season accepted results observed before the cutoff update the Phase 7
   online team strengths. Later results cannot enter the forecast.
6. Expected lineups are selected from real canonical player records, recent
   performances, current squad memberships when available, transfer observations,
   and availability reports observed before the cutoff.
7. The complete feature snapshot, both expected lineups, outcome distribution,
   score matrix, statistics distribution, deterministic seed, and event sequence
   are written in one transaction.
8. Only after every artifact passes validation does the prediction become
   `active_locked`. A failed transaction publishes nothing partial.
9. The public API gradually reveals the stored sequence on a shared one-minute
   server clock.

## Official model authority

The Phase 7 dynamic Poisson/Dixon-Coles goal model remains the official source of
expected goals, score probabilities, and win/draw/loss probabilities. Prior
accepted results from the active season update its attack and defence strengths
chronologically.

The Phase 12 artifact predicts the supported match statistics. Its training
pipeline contains median imputers. Until the full live Phase 8 feature state is
materialized in the operational database, unavailable non-goal feature values
are explicitly stored as `null` and use those fitted training medians. The
snapshot records this fallback; it is not hidden.

Player availability and expected lineups affect which real players appear in
the stored simulation. They do not silently replace the Phase 7 outcome model,
because the Phase 10 player-impact candidate and Phase 11 ensemble failed their
promotion gates.

## Real names and coverage failures

Official jobs never invent club or player identities. Team names come from the
canonical `clubs` table and player names from `players`. Shirt numbers use an
observed squad value when present; otherwise a clearly labelled
`presentation_slot` number is stored for layout only.

If either club lacks 11 eligible starters, a goalkeeper, or at least three
substitutes, generation returns `insufficient_lineup_coverage`. The job is
retried without publishing a forecast. After the configured attempt limit it is
marked failed for operator review. This is safer than presenting fictional
players as a real prediction.

## Leases, retries, and idempotency

- Job leases expire, so a crashed worker cannot hold a fixture forever.
- A worker stores only a short safe error code in `job_runs`; secrets and raw
  provider responses do not enter error fields.
- Retry timing and maximum attempts are configured through environment values.
- The database permits only one active official prediction per `match_uuid`.
- If a duplicate current-revision job reaches the writer after an official
  prediction exists, it returns the existing prediction rather than rerolling.
- A simulated-standings recalculation job is queued only after a new official
  prediction locks.

## Postponements and schedule revisions

Postpone, cancel, and reschedule commands lock the match first and cancel every
pending, leased, or running generation job for the old schedule. This lock order
also prevents a stale worker from racing a schedule change.

If a prediction already exists, it becomes `voided` and remains available to
audit tools. It disappears from public active-forecast queries. A reschedule
keeps the same canonical `match_uuid`, creates a new schedule revision, moves
`prediction_due_at` to 24 hours before the revised kickoff, and creates one new
revision-scoped generation job.

## Shared one-minute presentation

`GET /api/matches/{match_uuid}/forecast` returns these product states:

- `countdown`: T-24 has not arrived.
- `generating`: the due job is queued, leased, or running.
- `live`: the locked stored sequence is being revealed.
- `complete`: the one-minute presentation reached full-time.
- `postponed` or `cancelled`: there is no active public forecast.
- `unavailable`: generation exhausted its retries or an active artifact is
  incomplete.

The replay clock is fixed to 25 seconds for the first half, 10 seconds for the
interval, and 25 seconds for the second half. Scoreboard values and visible
statistics are recalculated only from already revealed events. Final score and
final statistics are absent from the response until full-time. Every viewer sees
the same phase based on `presentation_started_at`, including after refresh or on
another device.

## Local operation

Apply the migration and run a one-shot cycle:

```powershell
alembic upgrade head
.\scripts\run-forecast-dispatcher.ps1
```

The command performs no automatic provider synchronization. It consumes the
canonical data already stored in PostgreSQL and the two locally configured,
checksum-verified model artifacts. Deployment scheduling is deferred to the
deployment phase.

## Configuration

- `GOAL_MODEL_PATH` and `GOAL_MODEL_SHA256`
- `STATISTICS_MODEL_PATH` and `STATISTICS_MODEL_SHA256`
- `FORECAST_DISPATCH_BATCH_SIZE`
- `FORECAST_JOB_LEASE_SECONDS`
- `FORECAST_JOB_MAX_ATTEMPTS`
- `FORECAST_RETRY_DELAY_SECONDS`
- `SIMULATION_PRESENTATION_SECONDS` (fixed to 60 for the product)

## Verification

Phase 14 tests cover one-time enqueueing, exclusive job claims, time-cutoff
rejection, atomic artifact creation, duplicate-generation reuse, database
immutability, synchronized event visibility, and final-result withholding.
