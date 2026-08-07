# Phase 2 Foundation

The foundation separates web presentation, API/domain services, modeling code,
provider contracts, and deployment configuration.

## Local prerequisites

- Python 3.12
- Node.js 24 and pnpm 11
- Docker Desktop or another Compose-compatible runtime for local PostgreSQL

## Python setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Install the committed lock instead when reproducing the exact verified
environment:

```powershell
python -m pip install -r requirements.lock
```

When refreshing that lock, use `pip>=25,<26` because the current `pip-tools`
release is not compatible with the internal API removed in pip 26.

## Database

```powershell
docker compose up -d postgres
alembic upgrade head
```

The initial domain migration was added in Phase 3. Apply it with
`alembic upgrade head`.

The Compose database binds to host port `55432` by default to avoid collisions
with an existing PostgreSQL installation. Override it with `POSTGRES_PORT`.

## API

```powershell
uvicorn prem_engine_api.main:app --reload --app-dir backend
```

The foundation health endpoint is available at `GET /health`.

## Frontend

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
pnpm dev
```

## Contract probe

Set `KICKOFF_API_KEY` in the local process environment, never in a committed
file, then run:

```powershell
python backend/scripts/probe_kickoffapi.py
```

The probe performs at most four read-only requests and saves shapes rather than
provider values.
