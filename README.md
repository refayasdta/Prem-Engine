# Prem Engine

Prem Engine is a local Premier League forecasting and simulation platform. Each browser creates
one device-specific saved simulation per fixture schedule revision when its user presses Play,
then compares that timeline with the real result. Simulated and real-world standings remain
separate.

## Cloneable local quick start

The active product direction is a self-contained local installation. After installing Git and
Docker, start the complete foundation stack with:

```powershell
git clone <repository-url>
cd Prem-Engine
docker compose up --build
```

Open `http://localhost:3000`. PostgreSQL, migrations, idempotent initialization, FastAPI, the
production Next.js server, and the local worker all run inside Compose. PostgreSQL is not published
to the host or LAN.

The application starts without a provider key and shows a setup-required state. To enable current
fixture synchronization, copy `.env.example` to the ignored `.env` file, set `KICKOFF_API_KEY`, and
restart Compose. The key remains server-side. The worker performs a full startup reconciliation,
refreshes the active fixture window every four hours, refreshes player context daily, and reports
progress or a safe error code in the browser.

```powershell
# Stop while preserving the database, raw captures, and local model volume
docker compose down

# Restart without rebuilding
docker compose up

# Destructive reset: permanently removes all local application data
docker compose down -v
```

> **Warning:** `docker compose down -v` deletes the local database, simulations, raw captures, and
> locally trained model artifacts. Ordinary `down`, restart, rebuild, and host reboot operations
> preserve the named volumes.

The local transition is being delivered in bounded milestones. The foundation Compose topology,
safe unconfigured startup, audited synchronization, chronological Phase 7 catch-up training, and
per-device Play lifecycle are implemented. Local operations and hosted-code removal follow the
acceptance sequence in [the cloneable local architecture](docs/deployment/CLONEABLE_LOCAL_ARCHITECTURE.md).

Completed matchweeks are refitted in order using the approved Phase 7 configuration and all
eligible historical plus current-season results known at the cutoff. Postponed fixtures do not
block later matchweeks. Corrections and replayed fixtures create new immutable cutoff revisions;
the previous verified model remains active until the replacement artifact and provenance checksums
have been persisted successfully.

Play unlocks exactly 24 hours before the current canonical kickoff and remains available through
exactly 45 minutes after kickoff. The backend enforces that inclusive window, fixture freshness,
and current schedule revision. A random browser-local UUID partitions simulations, standings, and
evaluation without fingerprinting. Repeated or concurrent Play calls return the same stored result;
missed and void revisions never add games, goals, or points.

## Project status

Phases 1 through 15 and Phases 16A–16B are complete. The platform foundation now includes audited,
quota-aware KickoffAPI ingestion plus a provenance-preserving historical match
pipeline, a chronologically evaluated three-outcome Elo baseline, and a dynamic
Poisson goal and scoreline model backed by a strict 24-hour pre-match feature
pipeline. Phase 9 also evaluates calibrated tabular classifiers and transparently
records that the standalone candidate did not pass the promotion gate against
Elo and the goal model. Phase 10 adds canonical player context, expected lineups,
availability and transfer features, plus a coverage-gated training path. Its
reference model was initially blocked because historical player coverage was
not adequate. A follow-up public historical FPL audit and import added 66,665
player-match performances across all 2,280 target fixtures. The normalized
feature dataset passed its coverage gate at 96.0%. The approved manual training
run completed, but the player-impact candidate performed worse than the Phase 7
goal model on the untouched holdout and was rejected for official forecasts.
Phase 11 then tested 286 chronological convex ensembles across Elo, goals,
tabular, and player forecasts. Its selected 90% Elo/10% player blend also failed
the promotion gate, so Phase 7 remains the approved forecasting benchmark.
Phase 12 adds calibrated detailed-statistic models and safe fallbacks for
half-time goals, shots, shots on target, corners, fouls, and cards. Seven of 14
targets passed their holdout gates; possession and provider xG remain explicitly
unsupported because the historical export has no labels for them. Phase 13 turns
the locked goal and statistic forecasts into one deterministic, checksum-protected
match payload whose score, event feed, lineups, and statistics agree exactly. A
browser preview replays that stored payload without regenerating the match.
Phase 14 adds the automatic T-24 lifecycle: revision-scoped job scheduling,
expiring database leases, time-safe feature snapshots, real canonical player
lineups, atomic forecast locking, postponement-safe replacement jobs, and a
public synchronized replay endpoint. The endpoint never exposes future events or
the simulated final result before the shared one-minute presentation reaches
full-time. Phase 15 adds 34 leakage-safe observed-shape and measurable
style-proxy features. Its readiness build covers all 2,280 fixtures and passed
the training gate. The user's manual run completed, but the tactical candidate
was worse than Phase 7 on every primary holdout measure and was rejected. The
frontend lists real canonical fixtures and displays their real clubs, crests,
expected players, and stored synchronized simulations under
`/matches/{match_uuid}`. Phase 16A completes the public-facing product shell,
dashboard, fixture index, match lifecycle states, five-color responsive design,
accessibility baseline, and share metadata. The fictional Phase 13 route remains
outside normal product navigation as an isolated developer lab. Phase 16B adds
internally calculated real, simulated, and same-fixture comparison tables plus
live evaluation of every official forecast paired with an accepted real result.

- [Phase 1 feasibility report](docs/phase-1/FEASIBILITY_REPORT.md)
- [System architecture](docs/architecture/SYSTEM_ARCHITECTURE.md)
- [Fixture and forecast lifecycle policy](docs/architecture/LIFECYCLE_POLICY.md)
- [Phase 2 local setup](docs/phase-2/FOUNDATION.md)
- [Phase 3 domain schema](docs/phase-3/DOMAIN_SCHEMA.md)
- [Phase 4 data ingestion](docs/phase-4/DATA_INGESTION.md)
- [Phase 5 historical data](docs/phase-5/HISTORICAL_DATA.md)
- [Phase 6 Elo baseline](docs/phase-6/ELO_BASELINE.md)
- [Phase 7 goal model](docs/phase-7/GOAL_MODEL.md)
- [Phase 8 pre-match features](docs/phase-8/FEATURE_ENGINEERING.md)
- [Phase 9 calibrated tabular model](docs/phase-9/CALIBRATED_TABULAR_MODEL.md)
- [Phase 10 player impact and availability](docs/phase-10/PLAYER_IMPACT_AVAILABILITY.md)
- [API-Football historical player coverage audit](data/contracts/api-football/README.md)
- [Historical FPL player-data audit](data/contracts/fpl-historical/README.md)
- [Player-feature training readiness](data/contracts/models/PLAYER_FEATURE_READINESS.md)
- [Player-impact training result](data/contracts/models/PLAYER_MODEL_TRAINING_RESULT.md)
- [Phase 11 ensemble evaluation](docs/phase-11/ENSEMBLE_MODEL.md)
- [Phase 12 detailed statistics](docs/phase-12/DETAILED_STATISTICS.md)
- [Phase 13 quick-match simulation](docs/phase-13/QUICK_MATCH_SIMULATION.md)
- [Phase 14 automated forecast lifecycle](docs/phase-14/AUTOMATED_FORECAST_LIFECYCLE.md)
- [Phase 15 tactical inference and real-data UI](docs/phase-15/TACTICAL_INFERENCE_AND_REAL_UI.md)
- [Phase 15 tactical training result](data/contracts/models/TACTICAL_MODEL_TRAINING_RESULT.md)
- [Phase 16A core product UI](docs/phase-16a/CORE_PRODUCT_UI.md)
- [Phase 16B standings and evaluation](docs/phase-16b/STANDINGS_AND_EVALUATION.md)
- [Rate-limiting security controls](docs/security/RATE_LIMITING.md)
- [T-24 forecast rehearsal](docs/security/T24_REHEARSAL.md)
- [Pre-deployment operational hardening](docs/security/PRE_DEPLOYMENT_OPERATIONS.md)
- [Deployment runbook](docs/deployment/DEPLOYMENT_RUNBOOK.md)

## Development

The supported local toolchain is Python 3.12, Node.js 24, pnpm 11, and
PostgreSQL 16. See the Phase 2 setup guide for commands and environment details.

Run all available checks with:

```powershell
.\scripts\check.ps1
```

## Phase 10 manual workflow

After placing normalized player input files under
`data/processed/player_context/`, build the player-enhanced export and request
training with:

```powershell
.\scripts\export-player-context.ps1
.\scripts\build-player-features.ps1
.\scripts\train-player-impact-model.ps1
```

The commands default to human-readable output. Training exits cleanly with a
detailed blocked-readiness report until the historical coverage gate passes; it
does not manufacture or promote a sparse model. The 2026-08-10 reference run
passed the coverage gate but failed the promotion gate, so Phase 7 goals remains
the official benchmark.

## Phase 11 ensemble workflow

Run the deterministic convex-weight evaluation with:

```powershell
.\scripts\train-ensemble-model.ps1
```

The reference run evaluated 286 blends and rejected the selected ensemble. Its
artifact is retained locally for audit but is not approved for official use.

## Phase 13 simulation preview

Regenerate the fixed fictional preview payload, then run the frontend:

```powershell
.\scripts\generate-simulation-preview.ps1
cd frontend
pnpm dev
```

Open `http://localhost:3000/simulation-preview`. Play, pause, seek, and restart
the fixed one-minute replay. Refreshing the page loads the same seed and checksum,
so it cannot silently produce a different match.

## Phase 14 automatic lifecycle (retained historical workflow)

After applying migrations and configuring the two approved artifact paths, run
one local dispatcher cycle with:

```powershell
.\scripts\run-forecast-dispatcher.ps1
```

The hosted design invoked the same one-shot command every minute. A
cycle creates any missing current-revision jobs, leases a bounded due batch, and
generates each complete prediction transactionally. It also consumes the queued
simulated-standings recalculation after the stored presentation becomes fully
revealable. The browser reads
`GET /api/matches/{match_uuid}/forecast`. The active local product replaces that automatic shared
path with device-scoped `GET /api/matches/{match_uuid}/forecast?device_uuid=...` and
`POST /api/matches/{match_uuid}/play`; old shared simulations remain read-only audit records.

Refresh current squads, availability, transfers, confirmed lineups, and
post-match player performances with a quota-bounded cycle:

```powershell
.\scripts\sync-player-context.ps1 -Season 2026
```

The default uses no more than 16 KickoffAPI requests and is intended for one
daily scheduler invocation. See the operational-hardening guide for its request
distribution and the independent daily and rolling-minute safeguards.

## Phase 15 tactical workflow

Build the audited 134-feature dataset, then run the model training yourself:

```powershell
.\scripts\build-tactical-features.ps1 -Force
.\scripts\train-tactical-model.ps1
```

The reference build passed readiness at 97.5% style coverage and 58.7%
observed-shape coverage. The manual candidate run was rejected with 1.0794
holdout log loss versus Phase 7's 1.0089. Phase 7 therefore remains the official
outcome and scoreline model.

For the real-data browser path, start FastAPI on port 8000 and the frontend on
port 3000. The homepage lists canonical upcoming fixtures and links to
`/matches/{match_uuid}`. The fictional `/simulation-preview` is only a lab.

## Phase 16A product UI

Start the backend and frontend, then open `http://localhost:3000`. The public
product includes the dashboard, `/fixtures`, and official match pages. It never
substitutes fictional clubs or players when canonical data is missing. The two
standings views and post-match evaluation are delivered in Phase 16B. Deployment
and production operations are reserved for Phase 16C.

## Phase 16B standings and evaluation

With the backend and frontend running, open `/standings` for the separate real
and simulated tables and `/evaluation` for live official-forecast metrics. The
fair-comparison table uses only fixtures that have both a stored simulation and
an accepted real result, preventing unequal matches-played counts from distorting
the comparison. See the Phase 16B guide for metric definitions and exclusions.
