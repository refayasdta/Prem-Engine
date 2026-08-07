# Fixture and Forecast Lifecycle Policy

Date: 2026-08-07

## Canonical match identity

Every match has an internal UUID named `match_uuid`. External fixture IDs are
references, not primary identities.

Conceptual identity tables:

```text
matches
  match_uuid UUID primary key

match_external_references
  provider
  external_fixture_id
  match_uuid
  observed_from
  observed_until
  unique(provider, external_fixture_id)

fixture_schedule_revisions
  revision_uuid
  match_uuid
  kickoff_at
  provider_status
  observed_at
  superseded_at
```

More than one provider fixture ID may map to the same `match_uuid`. Automatic
matching uses competition, season, home team, away team, and kickoff proximity.
Ambiguous matches enter a review state instead of being silently merged.

## Fixture states

Canonical states:

- `scheduled`
- `postponed`
- `cancelled`
- `started`
- `suspended`
- `finished`
- `abandoned`
- `awarded`

Provider statuses are mapped to these states while retaining the original value.

## Forecast states

- `pending`: prediction window has not been reached.
- `generating`: a leased job is building the snapshot and artifacts.
- `active_locked`: the official active immutable version.
- `voided`: retained for audit but excluded from all active product calculations.
- `evaluated`: active locked forecast with accepted actual data and evaluation.
- `failed`: generation failed and can be retried only while no active version
  exists.

A database constraint permits at most one `active_locked` or `evaluated`
prediction for a `match_uuid`. Historical voided versions remain available to
administrators and audit tools.

## Normal pre-match lifecycle

1. The scheduler calculates `prediction_due_at = kickoff_at - 24 hours`.
2. A dispatcher claims the due match with an idempotent job key.
3. The job uses only information whose source observation time is not later than
   the feature cutoff.
4. It creates an immutable feature snapshot.
5. The expected-lineup model selects starters, substitutes, and formation with
   uncertainty metadata.
6. The forecasting model creates result, score, expected-goal, and statistics
   distributions.
7. The simulator samples one result and generates a complete consistent event
   timeline from a recorded seed.
8. Snapshot, predicted lineup, forecast, statistics, simulation, model version,
   seed, and cutoff are committed atomically as `active_locked`.
9. The simulated standings are recalculated from all active simulations.

If generation fails, no partial official prediction is published.

## Frontend replay

The simulation is generated once by the backend. Opening the match page reads the
stored simulation and gradually reveals its timestamped events. Refreshing,
reopening, or watching from another device produces the same lineup, events,
statistics, and result.

The frontend cannot request a reroll. Presentation time and football minute are
derived from the stored timeline and do not affect the canonical simulation.

## Predicted and real lineups

The predicted lineup is locked with the forecast approximately 24 hours before
kickoff. A confirmed real lineup may be ingested later and displayed separately.
It cannot change the active forecast. After the match, evaluation may compare:

- Predicted starters versus actual starters.
- Predicted formation versus actual formation.
- Player starting probabilities versus observed selections.

## Postponement and rescheduling

### Announced before generation

1. Add a schedule revision with the new kickoff.
2. Supersede the old schedule revision.
3. Recalculate `prediction_due_at`.
4. Do not create or void a prediction because none exists.

### Announced after generation

In one transaction:

1. Mark the active prediction version `voided` with reason `fixture_postponed`.
2. Void its predicted lineup and simulation through the owning prediction
   version rather than deleting audit records.
3. Exclude it from public active-forecast queries.
4. Add the revised kickoff schedule.
5. Recalculate the simulated standings, which now exclude the voided simulation.
6. Schedule a new generation job 24 hours before the revised kickoff.

The replacement receives a new prediction version UUID but retains the same
`match_uuid`. It becomes the only active official prediction.

## Exceptional fixtures

- Cancelled: void any active prediction and exclude its simulation from the
  simulated table.
- Abandoned with a replay: treat the replay as a schedule revision of the same
  canonical match unless competition rules identify it as a distinct match.
- Abandoned but officially declared complete: accept the official result for the
  real table and flag its forecast evaluation as exceptional.
- Awarded result: use the final official result for the real table, but exclude
  it from ordinary model score and event-statistics accuracy metrics.
- Suspended and resumed without a new fixture: retain the original forecast and
  wait for the official final result.
- Corrected score or statistics: create a new actual-data revision, recalculate
  real standings and evaluation, and leave the forecast unchanged.

## Real-world standings

The canonical real-world table is derived only from accepted official results in
`finished`, officially completed `abandoned`, or `awarded` states. Provider
standings are validation data only.

The table implements Premier League points and tie-break rules as versioned
competition rules. Recalculating from canonical results must reproduce every
stored snapshot.

## Simulated standings

The simulated table is derived only from active locked simulations. It updates as
each fixture receives its simulation, usually 24 hours before kickoff.

Consequences:

- Its matches-played count can differ from the real table.
- A voided postponed simulation disappears from its calculations.
- A replacement simulation enters it only when the new prediction locks.
- It never contributes to the real table.

The UI must show matches played for both tables. In addition to the full current
tables, a fair comparison view should compare real and simulated standings over
the same set of fixtures that have accepted real results.

## Immutability and audit

Application code must not update locked prediction payloads. Corrections create a
new version or void the active version under an allowed lifecycle transition.
Enforcement will use:

- Restricted database roles.
- State-transition validation.
- Partial unique indexes for active versions.
- Append-only lifecycle events.
- Checksums for snapshots and artifacts.
- Tests proving that ordinary ingestion cannot mutate forecasts.

This policy reconciles forecast immutability with the approved postponement
exception: active forecasts are immutable, while formally voided versions remain
auditable and can be replaced for a materially rescheduled fixture.
