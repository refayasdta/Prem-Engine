# Phase 1 Feasibility Report

Date: 2026-08-07

Status: Conditional go

Prem Engine is feasible as a free-first portfolio deployment. The application
can be developed without paid infrastructure and can initially run with Vercel
Hobby, Google Cloud Run, Supabase Free, and Cloudflare R2. The architecture must
preserve clean upgrade paths because database size, scheduled reliability, and
provider coverage cannot be guaranteed indefinitely on free plans.

## Repository audit

The repository was an initial, effectively empty Git repository at the start of
Phase 1:

- One commit: `9a390fb` (`Initial commit`).
- One existing file: `README.md`.
- No source code, package manifests, environment files, tests, or local agent
  instructions.
- The primary checkout is on `main`.
- The Codex worktree used for this phase is detached at the same commit.

Before Phase 2 changes begin, the worktree should be placed on a `codex/`
feature branch. No branch was created during Phase 1.

## Agreed product scope

The complete extended roadmap is in scope, including:

- Historical and current-season ingestion.
- Elo, Poisson, Dixon-Coles, calibrated tabular models, and chronological
  evaluation.
- Predicted lineups, player availability, transfers, advanced match statistics,
  and measurable tactical features.
- One backend-generated and stored simulation per active prediction.
- A real-world standings table and a separate simulated standings table.
- Automated pre-match generation, post-match ingestion, evaluation, deployment,
  monitoring, and portfolio documentation.

## External data findings

### KickoffAPI

The public v2 documentation supports the main proposed integration:

- Native IDs with prefixes for leagues, teams, fixtures, and players.
- Legacy league ID resolution, including Premier League legacy ID `39`.
- `season=2026` examples for the 2026/27 Premier League season.
- Fixture filtering by league, season, date, team, and date range.
- Cursor pagination with `meta.nextCursor`.
- Fixture events, lineups, team statistics, and player statistics.
- Team form, injuries, transfers, standings, and projections.
- Rate-limit headers for limit, remaining requests, reset time, and request ID.

The documentation is not internally consistent. Its public page currently mixes
v1 and v2 sections: the visible account-status example and some aggregate
sections use v1 paths even though the v2 page describes native IDs and a
`{ data, meta }` envelope. The project must not freeze provider DTOs from the
documentation alone.

Required Phase 2 contract checks, using the user's key only after separate
approval:

1. Confirm the working account-status path and whether checking quota consumes a
   request.
2. Resolve league ID `39` and store the returned native ID rather than hard-code
   the documentation example.
3. Verify the plan exposes every required endpoint.
4. Capture representative response envelopes, types, nullable fields, headers,
   pagination behavior, and error bodies.
5. Confirm maximum page sizes and whether filtered fixture calls return all 380
   matches.
6. Measure actual coverage for injuries, transfers, squads, lineups, xG, events,
   team statistics, and player statistics.

No authenticated KickoffAPI call was made in Phase 1.

Official source: https://docs.kickoffapi.com/

### Historical data

Football-Data.co.uk supplies season CSV files for the Premier League. Its data
dictionary documents results, half-time results, shots, shots on target,
corners, fouls, cards, referee data, and betting odds where available.
Availability varies by season and column. Expected-goals values are not part of
the documented core schema.

The site describes the files as free to download and use for quantitative
testing, but its notes page does not state a broad redistribution license.
Therefore:

- Preserve source attribution and retrieval timestamps.
- Do not republish source CSV files as downloadable product assets.
- Keep betting odds as an optional benchmark dataset, not a user-facing betting
  feature.
- Confirm terms before redistributing any derived bulk dataset.

Official sources:

- https://www.football-data.co.uk/englandm.php
- https://www.football-data.co.uk/notes.txt

## KickoffAPI request-budget design

The account limit is 100 requests per day. The application will enforce an
internal usable ceiling of 85 and reserve 15 requests for corrections, retries,
and urgent fixture changes.

Indicative daily budget:

| Work | Expected requests |
| --- | ---: |
| Quota/status check | 1 |
| Current fixture window and status synchronization | 1-4 |
| Injuries and suspensions | 1-5 |
| Transfers | 0-5 |
| Squad refreshes, amortized across days | 0-10 |
| Completed-match events, lineups, statistics, players | 4 per match |
| Provider standings validation | 0-1 |
| Reserved capacity | 15 |

On a ten-match completion day, four post-match endpoints per fixture use about
40 requests. The remaining core operations should normally keep the total below
85, subject to measured pagination.

Budget rules:

- Never poll live matches for the user-facing quick simulation; it is already
  generated and stored.
- Compute recent form internally instead of calling a team-form endpoint for all
  20 clubs.
- Use the largest verified safe page size.
- Cache every successful response and let jobs share it.
- Refresh squads incrementally instead of fetching every club every day.
- Fetch detailed match data once after final status, then retry missing endpoint
  data with exponential backoff on later dispatcher runs.
- Stop optional work when 20 requests remain and core work when 15 remain.
- Record requested endpoint, request time, status, remaining quota, reset time,
  and request ID without recording the API key.

## Free-tier capacity

### PostgreSQL

Supabase Free currently allows a 500 MB database. Raw provider payloads and model
artifacts must not be stored in PostgreSQL.

Planning envelope for normalized data, including indexes:

| Data class | Initial planning range |
| --- | ---: |
| Six historical seasons of matches and team statistics | 10-30 MB |
| Current-season players, events, lineups, and statistics | 40-100 MB |
| Feature snapshots and predictions | 40-100 MB |
| Stored simulation events and evaluations | 25-75 MB |
| Indexes, migrations, audit metadata, and headroom | 50-100 MB |
| Estimated total | 165-405 MB |

These are design estimates, not measurements. Phase 3 must measure actual row and
index sizes with representative data.

Thresholds:

- 300 MB: warning and storage review.
- 375 MB: stop adding nonessential duplicated data.
- 400 MB: initiate migration or paid-tier decision.
- 450 MB: operational hard stop before the provider enforces read-only mode.

Official sources:

- https://supabase.com/pricing
- https://supabase.com/docs/guides/platform/database-size

### Object storage

Cloudflare R2 currently includes 10 GB-month of Standard storage. It will hold
compressed raw responses, historical source files, database exports, model
artifacts, and backtest reports.

Planning envelope for the first complete season:

- Raw API responses: 1-4 GB compressed, coverage dependent.
- Model artifacts and evaluation reports: 0.5-2 GB.
- Historical CSV sources and database backup exports: under 2 GB initially.

Alert at 7.5 GB and plan an upgrade or archival strategy at 8.5 GB.

Official source: https://developers.cloudflare.com/r2/pricing/

### Compute and scheduling

- Vercel Hobby hosts the personal, non-commercial Next.js interface.
- Cloud Run hosts the FastAPI container and scales to zero at low traffic.
- One Cloud Scheduler entry invokes a dispatcher.
- The dispatcher claims due jobs from PostgreSQL and starts the appropriate Cloud
  Run Job.
- Expensive initial training and walk-forward backtests run locally. Production
  jobs perform lightweight inference and periodic validated retraining only when
  measured to fit the allowance.

Cloud Scheduler currently includes three free jobs per billing account, so one
dispatcher leaves capacity for two operational jobs if later required. Google
Cloud requires billing configuration even when usage stays within free limits;
budgets, quotas, and alerts are mandatory before deployment.

Official sources:

- https://vercel.com/docs/plans/hobby
- https://cloud.google.com/run/pricing
- https://cloud.google.com/run/docs/create-jobs
- https://cloud.google.com/scheduler/pricing

## Feasibility verdict

The project is technically feasible and the selected architecture is compatible
with the complete roadmap. Phase 2 can proceed after approval, but it must begin
with a feature branch and provider contract probes before application schemas are
treated as stable.

Major continuing risks:

1. KickoffAPI endpoint and field coverage on the user's plan.
2. The 100-request daily ceiling during congested or correction-heavy days.
3. Supabase's 500 MB normalized-data limit.
4. Incomplete player availability and tactical data.
5. Historical-source redistribution terms.
6. Free-tier policy changes and the absence of production service guarantees.

None of these risks prevents development. Each has an explicit validation,
fallback, or upgrade path.
