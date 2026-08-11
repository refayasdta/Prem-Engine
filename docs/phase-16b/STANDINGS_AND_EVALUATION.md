# Phase 16B: Standings and evaluation

Phase 16B makes Prem Engine accountable at season level. It adds two public
tables, a same-fixture comparison, and a match-by-match forecast ledger without
altering any locked prediction or retraining the official Phase 7 goal model.

## Public routes

- `/standings` shows the full real and simulated tables side by side.
- `/evaluation` shows live aggregate metrics and every paired match.
- `GET /api/standings` returns canonical tables for the current or latest season.
- `GET /api/evaluation` returns official-forecast evaluation for that season.

Both backend endpoints accept an optional `season_uuid` query parameter. An
unknown explicit UUID returns `404`; an empty database returns an honest empty
response rather than sample clubs or metrics.

## Real table

The real table includes only accepted result revisions for matches whose
canonical status is finished, officially completed abandoned, or awarded. It
does not consume the provider standings endpoint.

Premier League ordering is calculated with:

1. points;
2. goal difference;
3. goals scored;
4. club name as a deterministic display fallback when official criteria remain
   tied.

The calculation contract is versioned as
`premier-league-v1-points-gd-gf`. Points use the standard 3/1/0 rules.

## Simulated table

The simulated table includes only stored simulations owned by the one active
locked or evaluated prediction for each match. Voided predictions are excluded.
A simulation does not enter the public table until its fixed 60-second reveal
has completed, preventing the table from leaking a simulated result before the
official match page reveals it.

Because forecasts lock 24 hours before kickoff, the real and simulated tables
can legitimately have different matches-played counts.

## Fair comparison

The fair view intersects the canonical match UUIDs used by both timelines, then
recalculates two tables using only that identical fixture set. This answers the
question “what would the table look like if the same completed matches had
followed the stored simulations?” without allowing the simulated timeline to be
one or more rounds ahead.

## Live evaluation

A fixture enters evaluation only when it has:

- one active locked or evaluated prediction;
- one stored simulation;
- one currently accepted real result; and
- an officially completed canonical match status.

Normal accepted results contribute to:

- highest-probability outcome accuracy;
- multi-class log loss;
- multi-class Brier score;
- ranked probability score;
- expected calibration error;
- mean absolute expected-goal error per team;
- stored-simulation outcome accuracy; and
- stored-simulation exact-score accuracy.

Lower is better for every metric except the three accuracy values. The formulas
match the project’s historical evaluation conventions. When result ingestion
pairs an active forecast with a result, the prediction lifecycle state advances
from `active_locked` to `evaluated`; the locked payload remains immutable.

Awarded results remain visible in the ledger and standings but are excluded from
ordinary model metrics because the recorded score was not produced by normal
match play. Their exclusion is counted explicitly. Accepted abandoned results
are marked by their result kind and may be reviewed as exceptional evidence.

## Integrity and freshness

Every response is recalculated from current canonical PostgreSQL rows and carries
its calculation version and server calculation time. Provider standings cannot
replace either table. Result corrections create a new accepted revision, so the
next read recalculates standings and metrics without modifying the prediction.

Phase 16C will schedule production ingestion, cache or persist calculated views
where operationally useful, and add monitoring and deployment controls.
