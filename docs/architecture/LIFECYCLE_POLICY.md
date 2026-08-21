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

## Legacy shared forecast states

The database retains these states so simulations created by the earlier shared-forecast design remain
readable:

- `pending`: prediction window has not been reached.
- `generating`: the historical workflow was building the snapshot and artifacts.
- `active_locked`: the official active immutable version.
- `voided`: retained for audit but excluded from all active product calculations.
- `evaluated`: active locked forecast with accepted actual data and evaluation.
- `failed`: historical generation did not complete.

A database constraint permits at most one `active_locked` or `evaluated`
prediction for a `match_uuid`. Historical voided versions remain available to
administrators and audit tools.

## Active device-specific lifecycle

1. Fixture synchronization stores the current kickoff and schedule revision.
2. Play is disabled before `kickoff - 24 hours` and after `kickoff + 45 minutes`.
3. Inside that inclusive window, the user presses Play and supplies a random browser-local device UUID.
4. The backend verifies fixture freshness, status, schedule revision, and time window.
5. The Phase 7 model and pinned detailed-statistics model create a complete simulation using only
   information available at the cutoff.
6. The lineup, score, events, statistics, model provenance, seed, device UUID, and schedule revision
   are committed atomically.
7. Repeated or concurrent requests for the same device and revision return the existing simulation.
8. The device's simulated standings include the fixture only after Play has created that record.

If generation fails, no partial simulation is published and the user may retry while the window is
still open.

## Frontend replay

The simulation is generated once by the backend. Opening the match page reads the
stored simulation and gradually reveals its timestamped events. Refreshing or reopening with the
same device identity produces the same lineup, events, statistics, and result. Another device has an
independent identity and may receive a different stable simulation.

The frontend cannot request a reroll. Presentation time and football minute are derived from the
stored timeline and do not affect the simulation. The presentation uses 25 seconds for the first
half, 10 seconds for half-time, and 25 seconds for the second half. The API withholds future events,
final statistics, and the final score until that clock reaches them.

## Predicted and real lineups

The predicted lineup is locked with the forecast approximately 24 hours before
kickoff. A confirmed real lineup may be ingested later and displayed separately.
It cannot change the active forecast. After the match, evaluation may compare:

- Predicted starters versus actual starters.
- Predicted formation versus actual formation.
- Player starting probabilities versus observed selections.

## Postponement and rescheduling

### Announced before Play

1. Add a schedule revision with the new kickoff.
2. Supersede the old schedule revision.
3. Recalculate `prediction_due_at`.
4. Do not create or void a device simulation because none exists.

### Announced after Play

In one transaction:

1. Preserve the old revision and its device simulations as audit records.
2. Exclude those simulations from the current revision and current simulated table.
4. Add the revised kickoff schedule.
5. Open a new Play window relative to the revised kickoff.

The same device may Play again during the revised window. The replacement retains the same
`match_uuid` but belongs to the new schedule revision.

## Exceptional fixtures

- Cancelled: exclude device simulations from the current simulated table while retaining their audit
  records.
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

The simulated table is device-specific and derived only from simulations that device chose to Play
for current fixture revisions.

Consequences:

- Its matches-played count can differ from the real table.
- A voided postponed simulation disappears from its calculations.
- A replacement simulation enters it only when the device Plays the revised fixture.
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
