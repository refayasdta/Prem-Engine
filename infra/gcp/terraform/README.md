# Prem Engine Google Cloud runtime

This Terraform root defines the Cloud Run API, private forecast task handler, Cloud Tasks queue,
fixture synchronizer, player-context synchronizer, daily maintenance reconciler, unscheduled
migration job, three Cloud Scheduler entries, least-
privilege service accounts, Secret Manager access bindings, Artifact Registry, log-based metrics,
alerts, and an operations dashboard.

It deliberately does **not** create a database, database users, secret values, notification
channels, DNS, Vercel resources, or the GCS state bucket. Those are operator-controlled
dependencies. Secret values never belong in Terraform variables or state.

Public snapshots are rollout-gated. When `public_snapshot_enabled=true`, the forecast service plus
fixture and maintenance jobs receive write-only credentials for a dedicated R2 snapshot bucket.
Raw-response storage remains separate. Terraform does not grant public access: configure the
snapshot bucket's HTTPS read origin in Cloudflare, then use it as
`PREM_ENGINE_SNAPSHOT_BASE_URL` in Vercel.

## Safety defaults

- Every runtime image must use an `@sha256:` digest.
- `scheduler_paused` defaults to `true`.
- `forecast_task_scheduling_enabled` defaults to `false`; an initial apply creates no tasks.
- `public_snapshot_enabled` defaults to `false`; runtimes receive no snapshot credentials.
- `alerting_enabled` defaults to `false` until notification delivery is tested.
- A full plan refuses shared raw/public R2 buckets or credentials and refuses enabled alerting with
  no notification channel.
- Cloud Run deletion protection defaults to `true`.
- The migration job has no schedule and no automatic retry.
- API, worker, and migration database credentials are separate secrets and service accounts.

## Initializing and breaking the first-publish cycle

Create a private, versioned GCS state bucket through the platform-owner process, then initialize
with an environment-specific prefix. The state bucket must exist before `terraform init`; this
Terraform root intentionally does not own its own backend.

```powershell
terraform -chdir=infra/gcp/terraform init `
  -backend-config="bucket=REPLACE_STATE_BUCKET" `
  -backend-config="prefix=prem-engine/staging"
terraform -chdir=infra/gcp/terraform fmt -check
terraform -chdir=infra/gcp/terraform validate
```

On a new project, Artifact Registry must exist before the image workflow can publish, while the full
runtime plan requires already-published image digests. Break that cycle with one exceptional,
targeted bootstrap. Copy `terraform.tfvars.example` to an ignored environment file, replace every
identifier, keep all rollout gates closed, and create a saved plan containing only required APIs and
the Terraform-owned registry:

```powershell
$bootstrapDigest = '0' * 64
terraform -chdir=infra/gcp/terraform plan `
  -out=artifact-registry-bootstrap.tfplan `
  -var-file=PATH_TO_STAGING_TFVARS `
  -var="api_image=bootstrap.invalid/api@sha256:$bootstrapDigest" `
  -var="job_image=bootstrap.invalid/job@sha256:$bootstrapDigest" `
  -target=google_project_service.required `
  -target=google_artifact_registry_repository.containers
terraform -chdir=infra/gcp/terraform show artifact-registry-bootstrap.tfplan
terraform -chdir=infra/gcp/terraform apply artifact-registry-bootstrap.tfplan
```

The plan review must show only project-service enablement and the single Artifact Registry
repository. Never use these placeholder image references in an unscoped plan or runtime apply.
After configuring GitHub workload identity federation, publish both real images, replace the
placeholders with the emitted immutable digests, and discard the bootstrap plan.

Every subsequent plan is a normal, complete saved plan without `-target`:

```powershell
terraform -chdir=infra/gcp/terraform plan -out=staging.tfplan -var-file=PATH_TO_STAGING_TFVARS
terraform -chdir=infra/gcp/terraform show staging.tfplan
terraform -chdir=infra/gcp/terraform apply staging.tfplan
```

The first apply must retain `scheduler_paused=true`, `forecast_task_scheduling_enabled=false`,
`public_snapshot_enabled=false`, and `alerting_enabled=false`. A targeted bootstrap is not a normal
deployment and must never be reused for later changes. Follow the deployment guide before changing
any gate.
