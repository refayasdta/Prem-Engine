# Prem Engine deployment and maintenance guide

> **Superseded target:** The active product direction is the cloneable local architecture in
> [CLONEABLE_LOCAL_ARCHITECTURE.md](./CLONEABLE_LOCAL_ARCHITECTURE.md). These hosted operational
> instructions are retained as historical Phase 16C context until local replacement acceptance.

This guide turns the Phase 16C checklist into an operator sequence. It is intentionally split into
source preparation, staging acceptance, production release, and ongoing maintenance. Running any
cloud command, changing secrets, applying Terraform, invoking a job, migrating a real database, or
changing production traffic requires a separate approved change window.

The detailed evidence checklist remains in [DEPLOYMENT_RUNBOOK.md](./DEPLOYMENT_RUNBOOK.md).

## Runtime topology and ownership

| Component | Platform | Identity and access boundary |
| --- | --- | --- |
| Frontend | Vercel Next.js | Only the server-side proxy receives the active API origin token |
| API | Google Cloud Run service | Public ingress; `/api/*` requires the origin token; `/health` and `/ready` do not |
| Forecast delivery | Private Cloud Run service invoked by Cloud Tasks at exact T-24 | Worker database role plus public-snapshot-only R2 writer; OIDC/IAM required; no provider or raw-store credentials |
| Forecast queue | Google Cloud Tasks | Deterministic revision-scoped generation, reveal-finalization, and T-24 watchdog tasks; concurrency and dispatch rate both capped at one |
| Fixture sync | Cloud Run job, every four hours | Worker database role, KickoffAPI key, separate raw/snapshot R2 writers, and queue-enqueuer role |
| Player sync | Cloud Run job, daily at 02:15 UTC | Worker database role, KickoffAPI key, and R2 write credentials |
| Maintenance | Cloud Run job, daily at 03:30 UTC | Worker database role, snapshot R2 writer, and queue-enqueuer role; no provider credentials |
| Migration | Unscheduled Cloud Run job | Migration database role only |
| Database | Approved managed PostgreSQL provider | TLS required; API, worker, migration, backup, and restore roles are distinct |
| Raw provider captures | Cloudflare R2 | Private bucket; no public access; versioning/lifecycle set by the storage owner |
| Public delivery snapshots | Cloudflare R2 plus Vercel CDN | Separate public bucket with sanitized immutable JSON objects and atomic manifests |
| Model artifacts | Worker container image | Two approved files verified by SHA256 during build and before release |

Cloud Run and Scheduler resources are defined in `infra/gcp/terraform`. Vercel remains a separate
deployment because its project ownership, domain, and environment settings require the owner's
authenticated account.

## Required secrets and non-secret configuration

Create secret values directly in Google Secret Manager and Vercel; Terraform receives identifiers
only. Never place values in `.tfvars`, CI logs, source control, support tickets, or screenshots.

Google Secret Manager must contain:

- API-role `DATABASE_URL`;
- worker-role `DATABASE_URL`;
- migration-role `DATABASE_URL`;
- `KICKOFF_API_KEY`;
- active `API_ORIGIN_TOKEN` and, only during rotation, the previous token;
- `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` for private raw captures;
- `R2_SNAPSHOT_ACCESS_KEY_ID` and `R2_SNAPSHOT_SECRET_ACCESS_KEY` for public snapshots.

Create the API, worker, and backup login roles through the database-provider process without owner,
role-creation, database-creation, replication, bypass-RLS, or provider-superuser membership. Do not
put role passwords in a SQL file or command history. Connect through the direct migration-owner URL
and apply the repeatable grants only after reviewing the target and all three role names:

```powershell
$env:MIGRATION_DATABASE_URL = '<staging direct migration-owner URL>'
.\scripts\deployment\Grant-PostgresRuntimeRoles.ps1 `
  -ApiRole prem_engine_staging_api `
  -WorkerRole prem_engine_staging_worker `
  -BackupRole prem_engine_staging_backup `
  -ConfirmRoleGrants
Remove-Item Env:MIGRATION_DATABASE_URL
```

The script aborts when a supplied login is elevated, owns database objects, or inherits an
unexpected role. It grants current and future `public`-schema reads to API/backup and required DML
plus sequence access to the worker. Run migrations as the migration owner so default privileges
apply to future migration-created objects. Use a separate owner connection only for an isolated
restore target; never grant restore ownership to a runtime login. If a provider-created role
inherits an administrative role, replace or de-elevate it through the provider's approved process
before rerunning the grant script.

Vercel must contain `PREM_ENGINE_API_BASE_URL`, `PREM_ENGINE_ORIGIN_TOKEN`,
`PREM_ENGINE_SNAPSHOT_BASE_URL`, and `PREM_ENGINE_SNAPSHOT_STALE_IF_ERROR_SECONDS`. The token matches
the API's active `API_ORIGIN_TOKEN`. Configure `PREM_ENGINE_SITE_URL` with the canonical HTTPS
origin and set `PREM_ENGINE_HSTS_ENABLED=true` only for the production HTTPS domain. Never expose
these server settings with a `NEXT_PUBLIC_` prefix. Production database connections must use
`DATABASE_SSL_REQUIRED=true`.

The snapshot base URL is a non-secret HTTPS origin. The server proxy accepts snapshots only for
exact public routes; verifies manifest schema, object path, timestamps, length, SHA-256, and JSON;
and applies bounded CDN caching. `generating` and `live` forecasts always use the API so the
60-second reveal stays dynamic. Verified stale snapshots are used only after an origin failure,
and never after a countdown reaches T-24. Keep stale-if-error at or below 86400 seconds (the
example uses 21600).

### Public snapshot rollout

1. Create a dedicated R2 bucket and write-only credential. Do not reuse the raw-data bucket or
   credential.
2. Configure public reads through a stable HTTPS domain for derived `public/v1` content only.
   Never publish provider captures, operations/task state, credentials, or unreleased events.
3. Apply Terraform with `public_snapshot_enabled=false` first and verify runtime health.
4. Add the snapshot bucket and Secret Manager IDs, enable the gate in staging, and invoke
   maintenance once. Verify immutable payload objects precede their atomic manifests and that the
   recorded length/checksum matches each object.
5. Add the snapshot origin to Vercel Preview. Verify fresh hits, origin fallback, corrupt-manifest
   rejection, stale-if-error limits, and cache headers.
6. Rehearse a fixture: generation runs at T-24, finalization waits for the actual 60-second reveal
   boundary, and the watchdog checks the current revision at T-24 plus the monitoring grace. The
   first publication contains only currently visible state; finalization publishes the complete
   forecast and simulated standings. A rescheduled revision must be rejected safely.
7. Enable snapshot-publication alerts before production. Rollback by disabling the Terraform and
   Vercel snapshot settings; immutable historical objects do not need an emergency purge.

Create separate GitHub environments for staging and production. Configure workload identity
federation rather than a long-lived Google service-account key. The manual image publish workflow
expects `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_RELEASE_SERVICE_ACCOUNT`, `GCP_PROJECT_ID`,
`GCP_REGION`, and `ARTIFACT_REPOSITORY` in the protected environment.

## Build and release artifacts

1. Require green backend tests, migrations, Ruff, formatting, strict mypy, frontend tests, lint,
   typecheck, and production build from `ci.yml`.
2. Require `container-images.yml` to health-check, checksum-verify, vulnerability-scan, and generate
   SPDX SBOMs from the exact local images it pushes. A separate rebuild is not release evidence.
3. Manually dispatch the same workflow with `publish=true` from an approved commit.
4. Copy the two emitted `@sha256:` references into the environment's Terraform variable file.
5. Retain the commit SHA, image digests, SBOM artifacts, model checksums, Terraform plan, migration
   revision, and acceptance report as the release evidence bundle.

The approved embedded model hashes are:

- goals: `fe8a19c262b6a0d8aa02e01564f6c109eec2d16e237fa276e6a414967ecf0adc`;
- detailed statistics: `6859e2b0a6cd23382b795e68034b29548a6ac0a26fa9f08623cda5306cac4e12`.

## Staging deployment sequence

1. Create the private, versioned GCS state bucket outside this Terraform state and initialize the
   staging backend. If the Artifact Registry repository does not yet exist, run only the reviewed
   two-target bootstrap in `infra/gcp/terraform/README.md`; it enables required APIs and creates the
   Terraform-owned repository without deploying placeholder images.
2. Configure GitHub workload identity federation, publish the two containers, and record their real
   immutable digests. Create and test the managed PostgreSQL roles, backups, restore target, Secret
   Manager versions, R2 buckets, notification channels, Vercel project, and GitHub environment.
3. Generate and peer-review a complete saved Terraform plan with real image digests,
   `scheduler_paused=true`, `forecast_task_scheduling_enabled=false`,
   `alerting_enabled=false`, and deletion protection enabled.
4. Apply the reviewed plan. Record outputs, service accounts, image digests, and the API URL.
5. Verify `/health` returns 200 and `/ready` returns 200. A 503 from `/ready` blocks release.
6. Produce a pre-migration custom-format PostgreSQL backup using `Backup-Postgres.ps1`. Copy it to
   the approved encrypted backup location and independently verify its SHA256 metadata.
7. Rehearse restoring that backup into an isolated database with `Restore-Postgres.ps1`. Confirm row
   counts and run the API test suite against the restore.
8. Invoke the unscheduled migration job with `Invoke-MigrationJob.ps1`. Confirm `alembic current`
   reports the reviewed repository head before continuing.
9. Deploy the frontend preview with the staging API URL and matching origin token. Confirm direct
   unauthenticated `/api/*` access returns 401 while frontend server-proxied requests succeed.
10. Manually execute fixture sync once with task scheduling disabled, then player sync once. Confirm raw captures exist in R2,
   provider request ledger entries match calls, fixture identities are resolved, and no secret
   appears in logs.
11. Verify unauthenticated requests to all three private forecast task endpoints receive `403`, then enable task
    scheduling in staging and run fixture sync again. Select a real exact-kickoff fixture between 24
    hours and 30 days away. Confirm the deterministic generation/watchdog task set and one ledger
    row exist for its current revision. Cloud Tasks must invoke the service with OIDC at T-24, lock exactly one forecast,
    preserve the feature cutoff, and change the UI from countdown to the deterministic 60-second
    reveal. Rescheduling must retain the old audit record, create a new task, and make delivery of the
    old task exit successfully as stale without generating a forecast.
    Confirm the per-revision watchdog reports healthy after a successful forecast and emits a
    missing-T24 event only after the configured grace period.
12. Trigger each alert in staging with a controlled test signal and verify delivery and recovery.
    Enable alert policies only after notification routing is proven.
13. Run `production-acceptance.yml` against the fixture page. First verify a fresh general snapshot
    such as `standings/default`; after the reveal finalizer, rerun with
    `forecast/<match-uuid>` and expected lifecycle `complete`. Retain the snapshot integrity output,
    three-run Lighthouse report, and endpoint/security-header evidence.
14. Peer-review the second Terraform plan that enables alerts and unpauses schedules. Apply it only
    after the staging T-24 evidence is accepted.

## Scheduler and provider-budget proof

All cron expressions use `Etc/UTC`:

| Job | Schedule | Maximum intended KickoffAPI calls |
| --- | --- | --- |
| Fixture sync | minute 0 every four hours | 10 per run, 60 per day |
| Player sync | 02:15 daily | 16 per day |
| Maintenance/task reconciliation | 03:30 daily | 0 |

The planned maximum is 76 calls/day, below the application operational ceiling of 85 and the
provider hard limit of 100. Each individual ingestion run is also below the application ceiling of
25 calls/minute. The database-backed reservation ledger atomically refuses request 86, and the
rolling-minute guard refuses request 26. The client emits a quota warning when the committed
reservation reaches the configured threshold instead of waiting for daily maintenance. Scheduler
and Cloud Run retries do not bypass either guard.
Do not add manual provider calls without first checking the current UTC-day ledger.

## Production promotion

Repeat the staging sequence with production-specific state, database, secrets, R2 bucket,
notification channels, and Vercel environment. Do not copy staging database credentials or storage
keys. Keep schedules paused while the API, migration, frontend, and one-shot job checks run.

Promote the exact staging-approved commit and image digests. Run a fresh production backup before
the migration. Compare the production Terraform plan with staging for intentional differences only.
After smoke and acceptance checks pass, enable alerting first, verify telemetry, enable forecast
task scheduling, then unpause the three schedules. Record the release time, operator, reviewer,
database revision, frontend deployment, Cloud Run revisions, queue name, image digests, and first
successful scheduled executions.

## Monitoring and incident response

The API emits one-line JSON request events with a safe `X-Request-ID`. It does not log headers,
query values, credentials, connection strings, or provider payloads. Jobs and event-time watchdog
tasks emit stable event names for terminal forecast failure, task enqueue failure, stale task
delivery, missed T-24 forecasts, provider quota warnings, raw-storage failures,
snapshot-publication failures, and operational counts.

The Terraform dashboard covers API response classes, p95 latency, and Cloud Run job outcomes. Alert
policies cover API and private-forecast 5xx responses, any failed job execution, Scheduler errors,
task enqueue failures, stale deliveries, missed T-24 forecasts, terminal forecast retries, R2
failures, snapshot-publication failures, and provider quota warnings.

For an incident:

1. disable forecast task scheduling and pause all three Scheduler entries if repeated execution
   could increase damage or consume quota; pause the queue through the operator process when
   already-enqueued deliveries must also stop;
2. preserve request IDs, execution IDs, job UUIDs, UTC timestamps, image digests, and relevant logs;
3. check database readiness, quota ledger, R2 durability, recent secret versions, and job lease state;
4. do not manually mutate job rows or prediction versions;
5. use the bounded idempotent job path for a retry only after the cause is corrected;
6. document impact, recovery, missed forecasts, provider calls, and follow-up controls.

## Backups, retention, and restore tests

Enable provider-native encrypted daily backups and point-in-time recovery before staging data is
accepted. Retain daily backups for at least 30 days, weekly backups for 12 weeks, and pre-migration
release backups for the product's audit-retention period. Apply equivalent versioning and lifecycle
rules to the private R2 bucket. Final values must match the approved data-retention policy.

Once per quarter, restore the newest backup into an isolated target, verify the checksum before
restore, run migrations only if the rehearsal plan calls for them, compare critical table counts,
run health and API tests, and destroy the isolated target through the database-provider process.
Never test restore by overwriting staging or production.

## Rollback

Disable new task scheduling and pause schedules before rollback. For frontend regressions, promote the last known-good Vercel
deployment. For API or job regressions, apply a reviewed Terraform plan using the previous immutable
image digest; never reuse or overwrite a tag. Verify health, readiness, origin authentication, and a
one-shot job before resuming schedules.

Database migrations are forward-only by default. Prefer a reviewed corrective migration. Restore a
pre-migration backup only when incident command accepts the loss window, the exact target is verified,
and `Restore-Postgres.ps1` is invoked with its checksum, expected database name, and explicit
confirmation. Rotate compromised credentials using active/previous origin-token overlap, validate
the new token end to end, then remove the previous version.

## Maintenance cadence

- Daily: review alerts, failed executions, missed T-24 count, provider usage, and backup status.
- Weekly: inspect unresolved fixture identities, stuck leases, R2 lifecycle status, API error/latency
  trends, and dependency/security alerts.
- Monthly: patch base images and dependencies, rebuild/scan both images, review IAM and secret age,
  confirm budget assumptions, and test one non-destructive alert path.
- Quarterly: rehearse database restore, rotate appropriate credentials, review retention, audit
  service-account access, and run the full accessibility/security/performance acceptance workflow.
- Each season: update `season_start_year`, validate provider contracts and club mappings, prove the
  quota calculation again, and complete a staging T-24 rehearsal before production scheduling.
