# Prem Engine

Prem Engine is an autonomous Premier League forecasting and simulation platform.
It publishes one probabilistic forecast and one stored quick-match simulation for
each fixture, then compares them with the real result. Simulated and real-world
standings are maintained separately.

## Project status

Phases 1 through 8 are complete. The platform foundation now includes audited,
quota-aware KickoffAPI ingestion plus a provenance-preserving historical match
pipeline, a chronologically evaluated three-outcome Elo baseline, and a dynamic
Poisson goal and scoreline model backed by a strict 24-hour pre-match feature
pipeline.

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

## Development

The supported local toolchain is Python 3.12, Node.js 24, pnpm 11, and
PostgreSQL 16. See the Phase 2 setup guide for commands and environment details.

Run all available checks with:

```powershell
.\scripts\check.ps1
```
