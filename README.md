# Prem Engine

Prem Engine is an autonomous Premier League forecasting and simulation platform.
It publishes one probabilistic forecast and one stored quick-match simulation for
each fixture, then compares them with the real result. Simulated and real-world
standings are maintained separately.

## Project status

Phases 1 through 12 are complete. The platform foundation now includes audited,
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
unsupported because the historical export has no labels for them.

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
