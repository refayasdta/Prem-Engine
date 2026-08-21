# Cloneable local system architecture

Prem Engine is distributed as one Docker Compose application. Each installation owns its database,
raw provider captures, trained models, and device-specific simulations. No hosted control plane or
shared public database is required.

```text
Desktop or trusted-LAN browser
              |
       Next.js frontend
              |
        FastAPI backend
          /         \
 PostgreSQL       named volumes
                      |
             raw data and models

Local worker -> fixture/player synchronization
Local worker -> chronological matchweek training
```

## Compose services

- `postgres` is the installation's system of record and is not published to the host or LAN.
- `migrate` applies database migrations before application startup.
- `initialize` idempotently records installation metadata and prepares local state.
- `api` owns business rules and all database access used by the browser.
- `worker` performs bounded synchronization, reconciliation, and chronological local training.
- `frontend` serves the product and proxies `/api/*` to the backend over the private Compose network.
- `operations` is an on-demand profile for backup, restore verification, and diagnostics.

Only the frontend port is exposed. It binds to `127.0.0.1` by default; setting the documented LAN
binding explicitly permits phones on a trusted local network to connect.

## Data ownership and persistence

Named Docker volumes preserve PostgreSQL data, raw compressed provider responses, backup files, and
local model artifacts across container rebuilds and ordinary `docker compose down` operations. A
volume reset is the explicit destructive path. Provider credentials remain in the ignored host
`.env` file and are passed only to services that make provider requests.

KickoffAPI is the primary current-data source. The official FPL bootstrap endpoint is a separately
budgeted fallback for an affected club when the primary squad response is too sparse or lacks a
goalkeeper. Every outbound provider call remains quota guarded and auditable.

## Forecast and simulation lifecycle

The worker keeps canonical fixtures current, but it does not automatically create a shared match
simulation at T-24. Play becomes available from exactly 24 hours before kickoff through exactly 45
minutes after kickoff. A user action creates one immutable simulation for that browser's random local
device UUID and current fixture revision. Repeated or concurrent requests return that same record.

Different installations and devices are intentionally independent. A simulation made on a phone is
not expected to appear on a laptop unless both browsers use the same device identity; planned private
cross-device synchronization is documented separately and is not part of the public local edition.

## Model lifecycle

The approved Phase 7 model configuration is the official benchmark. The local worker catches up
completed matchweeks chronologically using only results known at each cutoff. A newly trained artifact
becomes active only after its model and provenance checksums are persisted successfully. The last
verified artifact remains active after a failed update.

## Historical compatibility

The schema and historical phase documentation retain records created by the former automatic/shared
forecast design so existing local databases remain readable. Active application code does not enqueue
Cloud Tasks, run a forecast dispatcher, publish public snapshots, or require Vercel, Google Cloud,
Neon, Cloudflare R2, Terraform, or hosted secret-management services.
