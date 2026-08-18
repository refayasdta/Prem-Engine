# Local operations, recovery, and trusted-LAN access

This runbook applies to the cloneable Docker Compose edition. It requires only Git, Docker, and
the host's normal shell. PostgreSQL and model tooling run inside one-shot containers; no host
PostgreSQL, Python, or Node.js installation is required.

## Service health, diagnostics, logs, and disk use

Run these commands from the repository root:

```powershell
docker compose ps
docker compose --profile operations run --rm operations diagnostics
docker compose logs --since 30m --tail 200 api worker frontend
docker system df
```

`docker compose ps` must report `healthy` for PostgreSQL, API, frontend, and worker. Diagnostics
reports the migration revision, critical row counts, simulation states, active local model
versions, worker state, today's provider-call count, and backup/model disk use. It never prints the
provider key or database password.

For a single service, use `docker compose logs --since 30m --tail 200 worker`. Add `--follow` only
while actively watching; press Ctrl+C to stop following without stopping the service.

## Consistent local backup

A backup contains:

- a PostgreSQL custom-format dump;
- the complete locally trained model volume;
- critical row counts and active-model metadata;
- safe release and creation metadata; and
- SHA-256 checksums for every included file.

Provider secrets and `.env` are deliberately excluded. Keep the bundle on an encrypted or
access-controlled disk if its fixture/simulation history is private.

Pause writers briefly, create the bundle, and restart them:

```powershell
docker compose stop api worker
docker compose --profile operations run --rm operations backup
docker compose start api worker
```

The command prints a name such as `prem-engine-20260818T120000Z`. Its ignored host directory is
`backups/<bundle-name>/`. If backup refuses because another database connection is active, confirm
that API and worker are stopped and retry. The frontend may remain running, but Play and data calls
will be unavailable during the short maintenance window.

Do not edit a completed bundle. Copy the entire directory, including `SHA256SUMS` and
`database-summary.txt`, when moving it to another disk.

## Safe restore rehearsal

Verify every important backup before relying on it:

```powershell
docker compose --profile operations run --rm operations verify prem-engine-20260818T120000Z
```

Verification checks every SHA-256, validates the model archive, restores the database into the
fixed disposable database `prem_engine_restore_verify`, compares critical counts and active-model
metadata, and then deletes the disposable database. It never overwrites the live database.

## Disaster restore

Restore is destructive: it replaces the live local database and model volume with the selected
bundle. First copy the current data elsewhere or take a new backup when possible. Resolve the exact
bundle name under `backups/`, stop all application writers/readers, and use the explicit database
confirmation:

```powershell
docker compose stop frontend api worker
docker compose --profile operations run --rm operations restore `
  prem-engine-20260818T120000Z RESTORE-prem_engine
docker compose up -d
docker compose --profile operations run --rm operations diagnostics
```

The restore refuses malformed bundle names, checksum failures, a wrong confirmation phrase, or
active database connections. After startup, confirm all services are healthy and inspect one saved
simulation, standings, and active model metadata.

## Ordinary shutdown, restart, and offline recovery

These commands preserve named volumes:

```powershell
docker compose down
docker compose up -d
docker compose ps
```

After time offline, the worker reconciles fixtures and missed model-training cutoffs. The browser
may truthfully show stale data until synchronization succeeds. Do not use `docker compose down -v`
for ordinary recovery: `-v` permanently deletes the database, simulations, raw captures, and local
models.

Before an upgrade, create and verify a backup. Then pull the desired revision and run
`docker compose up --build -d`; the migration service runs before API startup.

## Default network boundary

The default frontend binding is `127.0.0.1:3000`, so only the host computer can connect.
PostgreSQL, API, worker, migrations, initialization, and operations have no published ports and
remain on internal Compose networks.

Check the effective binding with:

```powershell
docker compose port frontend 3000
```

It should begin with `127.0.0.1` unless trusted-LAN access is intentionally enabled.

## Enable temporary trusted-LAN mobile access

The local edition has no user accounts. A device UUID separates simulations but is not
authentication. Enable LAN access only on a trusted private home/development network, never on a
public Wi-Fi network or by forwarding the router port to the internet.

1. In the ignored `.env`, set `PREM_ENGINE_HOST_BIND=0.0.0.0` and keep
   `PREM_ENGINE_FRONTEND_PORT=3000`.
2. Recreate the frontend: `docker compose up -d --force-recreate frontend`.
3. Find the host's private IPv4 address (`ipconfig` on Windows or `ip addr` on Linux/macOS).
4. Allow inbound TCP port 3000 only on the host's **Private** firewall profile. On Windows, an
   Administrator PowerShell can use:

   ```powershell
   New-NetFirewallRule -DisplayName "Prem Engine 3000 (Private LAN)" `
     -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3000 -Profile Private
   ```

5. From a phone on the same Wi-Fi, open `http://<host-private-ip>:3000`. `localhost` on the phone
   refers to the phone, not the desktop.

If it does not connect, confirm the host network is Private, the firewall rule exists, both devices
are on the same subnet, and the router is not using wireless client isolation. VPNs may also block
local routing.

Disable LAN access afterward by restoring `PREM_ENGINE_HOST_BIND=127.0.0.1`, recreating the
frontend, and removing the firewall rule:

```powershell
Remove-NetFirewallRule -DisplayName "Prem Engine 3000 (Private LAN)"
```

## Desktop and mobile acceptance checklist

For every supported browser/device combination:

1. Dashboard, fixtures, match, standings, evaluation, model, and 404 pages fit without horizontal
   scrolling at 200% text zoom.
2. Navigation and Play meet touch-target expectations in portrait and landscape.
3. The Play card has a visible hover/focus treatment and works with keyboard Enter/Space.
4. The one-minute presentation clock advances steadily, pauses at halftime, and resumes correctly
   after backgrounding and reopening the tab.
5. Closing/reopening the browser returns the same device simulation; a second mobile browser keeps
   a distinct device identity.
6. Screen-reader names describe navigation, teams, status, Play, commentary, and final state.
7. A Compose restart preserves the same simulation, standings, and evaluation state.

Responsive desktop emulation is useful but does not replace a final check on current Android
Chrome and iOS Safari before advertising those combinations as supported.
