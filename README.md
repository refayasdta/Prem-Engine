# Prem Engine

Prem Engine is an autonomous Premier League forecasting and simulation platform.
It publishes one probabilistic forecast and one stored quick-match simulation for
each fixture, then compares them with the real result. Simulated and real-world
standings are maintained separately.

## Project status

Phase 1 (architecture and feasibility) is complete. Phase 2 establishes the
frontend, API, modeling, data-contract, test, and deployment foundations.

- [Phase 1 feasibility report](docs/phase-1/FEASIBILITY_REPORT.md)
- [System architecture](docs/architecture/SYSTEM_ARCHITECTURE.md)
- [Fixture and forecast lifecycle policy](docs/architecture/LIFECYCLE_POLICY.md)
- [Phase 2 local setup](docs/phase-2/FOUNDATION.md)

## Development

The supported local toolchain is Python 3.12, Node.js 24, pnpm 11, and
PostgreSQL 16. See the Phase 2 setup guide for commands and environment details.

Run all available checks with:

```powershell
.\scripts\check.ps1
```
