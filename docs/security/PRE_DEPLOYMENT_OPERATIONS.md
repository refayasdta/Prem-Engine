# Pre-deployment operational hardening

The codebase now covers the four pre-deployment gaps identified in the readiness audit. Cloud
Scheduler activation and production alert routing still belong to the staging deployment step because
they require real Google Cloud resource identifiers and service accounts.

## Live forecast reads

The official match page no longer sends one request every second indefinitely from every open tab.
It now:

- elects one same-origin polling leader per match when the browser supports the Web Locks API;
- shares the leader's verified response with other tabs through `BroadcastChannel`;
- pauses network reads while the page is hidden;
- polls every 15 seconds while waiting, every three seconds while generation runs, and every two
  seconds during the 60-second presentation; and
- stops after a terminal `complete` or `cancelled` response.

Browsers without Web Locks retain the same adaptive intervals but poll per tab; current Chromium,
including the supported local browser path, uses the coordinated leader behavior.

A normal live presentation therefore needs about 30 forecast reads, leaving substantial headroom
inside the public 60-request rolling-minute limit.

## Simulated standings worker

`recalculate_simulated_standings` is now a supported dispatcher job type. Forecast locking schedules
the job for the end of the 60-second presentation, not its beginning. The worker leases the job with
the same PostgreSQL concurrency controls as forecast generation, calculates only simulations whose
final result is already revealable, appends a versioned `simulated` standings snapshot and rows, then
marks the job successful in the same transaction. Failures use the existing bounded retry policy.

The public standings API continues to calculate current tables on read. Persisted snapshots are the
auditable background record and no longer leave pending jobs unconsumed.

## Current player context

The current-data ingestion path now normalizes:

- provider players and external references;
- current squad memberships, positions, and shirt numbers;
- injury and suspension availability reports;
- transfers between mapped canonical clubs;
- confirmed fixture lineups; and
- post-match player minutes, starting state, position, rating, and provider statistics.

Every provider response still passes through the existing request ledger and append-only raw capture
before normalization. Unresolvable clubs, matches, or players are counted instead of being replaced
with invented identities.

Run one bounded cycle after the canonical fixture season has been imported:

```powershell
.\scripts\sync-player-context.ps1 -Season 2026
```

The default cycle can use at most 16 requests. It allocates up to three injury pages, two transfer
pages, reserves capacity for up to two completed matches (lineup plus player-performance calls),
then refreshes as many of the stalest squads as the remaining budget allows. With ten squad targets
per normal cycle, all 20 league
squads can be refreshed over two daily cycles. HTTP 404 coverage gaps are captured, counted, and do
not prevent the remaining targets from running.

KickoffAPI enforcement now has two local controls:

- 85 requests per UTC day out of the provider's 100-request allowance; and
- 25 requests in a rolling minute out of the provider's 30-request limit.

Both limits are database-coordinated and checked before outbound traffic. Provider-reported
remaining/reset headers remain an additional stop condition.

## Model artifacts

The forecast-job image copies the two exact checksum-pinned model binaries used by inference. CI
also fails when either binary is absent. The configured SHA-256 values remain:

- goals: `fe8a19c262b6a0d8aa02e01564f6c109eec2d16e237fa276e6a414967ecf0adc`;
- detailed statistics: `6859e2b0a6cd23382b795e68034b29548a6ac0a26fa9f08623cda5306cac4e12`.

## Staging handoff

At the start of deployment, create two scheduler invocations: the minute forecast dispatcher and a
daily player-context sync. Bind them to staging service accounts, run the T-24 rehearsal, inspect the
provider request ledger and standings snapshots, and configure failure/no-forecast alerts before
promoting the same configuration to production.
