locals {
  resource_name   = "${var.name_prefix}-${var.environment}"
  r2_endpoint_url = coalesce(var.r2_endpoint_url, "https://${var.r2_account_id}.r2.cloudflarestorage.com")
  common_labels = {
    application = "prem-engine"
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "terraform_data" "deployment_safety" {
  input = var.environment

  lifecycle {
    precondition {
      condition = !var.public_snapshot_enabled || (
        try(var.r2_snapshot_bucket_name != var.r2_bucket_name, false) &&
        try(var.r2_snapshot_access_key_id_secret_id != var.r2_access_key_id_secret_id, false) &&
        try(var.r2_snapshot_secret_access_key_secret_id != var.r2_secret_access_key_secret_id, false)
      )
      error_message = "Public snapshots must use a bucket and credentials separate from raw captures."
    }
    precondition {
      condition     = !var.alerting_enabled || length(var.notification_channel_ids) > 0
      error_message = "alerting_enabled requires at least one tested notification channel."
    }
  }
}

resource "google_project_service" "required" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudtasks.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "containers" {
  project       = var.project_id
  location      = var.region
  repository_id = "${local.resource_name}-containers"
  description   = "Immutable Prem Engine API and worker images"
  format        = "DOCKER"
  labels        = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_service_account" "api" {
  project      = var.project_id
  account_id   = "pe-${var.environment}-api"
  display_name = "Prem Engine ${var.environment} API"
}

resource "google_service_account" "forecast" {
  project      = var.project_id
  account_id   = "pe-${var.environment}-forecast"
  display_name = "Prem Engine ${var.environment} private forecast service"
}

resource "google_service_account" "task_invoker" {
  project      = var.project_id
  account_id   = "pe-${var.environment}-task-invoker"
  display_name = "Prem Engine ${var.environment} Cloud Tasks OIDC invoker"
}

resource "google_service_account" "fixtures" {
  project      = var.project_id
  account_id   = "pe-${var.environment}-fixtures"
  display_name = "Prem Engine ${var.environment} fixture synchronization"
}

resource "google_service_account" "players" {
  project      = var.project_id
  account_id   = "pe-${var.environment}-players"
  display_name = "Prem Engine ${var.environment} player synchronization"
}

resource "google_service_account" "maintenance" {
  project      = var.project_id
  account_id   = "pe-${var.environment}-maintenance"
  display_name = "Prem Engine ${var.environment} task reconciliation and monitoring"
}

resource "google_service_account" "migration" {
  project      = var.project_id
  account_id   = "pe-${var.environment}-migration"
  display_name = "Prem Engine ${var.environment} database migration"
}

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = "pe-${var.environment}-scheduler"
  display_name = "Prem Engine ${var.environment} Cloud Scheduler invoker"
}

locals {
  secret_bindings = {
    api_database = {
      secret_id = var.database_api_secret_id
      member    = google_service_account.api.member
    }
    api_origin = {
      secret_id = var.origin_token_secret_id
      member    = google_service_account.api.member
    }
    forecast_database = {
      secret_id = var.database_worker_secret_id
      member    = google_service_account.forecast.member
    }
    fixtures_database = {
      secret_id = var.database_worker_secret_id
      member    = google_service_account.fixtures.member
    }
    fixtures_kickoff = {
      secret_id = var.kickoff_api_key_secret_id
      member    = google_service_account.fixtures.member
    }
    fixtures_r2_id = {
      secret_id = var.r2_access_key_id_secret_id
      member    = google_service_account.fixtures.member
    }
    fixtures_r2_secret = {
      secret_id = var.r2_secret_access_key_secret_id
      member    = google_service_account.fixtures.member
    }
    players_database = {
      secret_id = var.database_worker_secret_id
      member    = google_service_account.players.member
    }
    players_kickoff = {
      secret_id = var.kickoff_api_key_secret_id
      member    = google_service_account.players.member
    }
    players_r2_id = {
      secret_id = var.r2_access_key_id_secret_id
      member    = google_service_account.players.member
    }
    players_r2_secret = {
      secret_id = var.r2_secret_access_key_secret_id
      member    = google_service_account.players.member
    }
    maintenance_database = {
      secret_id = var.database_worker_secret_id
      member    = google_service_account.maintenance.member
    }
    migration_database = {
      secret_id = var.database_migration_secret_id
      member    = google_service_account.migration.member
    }
  }
  optional_secret_bindings = var.origin_previous_token_secret_id == null ? {} : {
    api_origin_previous = {
      secret_id = var.origin_previous_token_secret_id
      member    = google_service_account.api.member
    }
  }
  snapshot_secret_bindings = !var.public_snapshot_enabled ? {} : {
    for pair in flatten([
      for runtime, member in {
        forecast    = google_service_account.forecast.member
        fixtures    = google_service_account.fixtures.member
        maintenance = google_service_account.maintenance.member
        } : [
        {
          key       = "${runtime}_snapshot_id"
          secret_id = var.r2_snapshot_access_key_id_secret_id
          member    = member
        },
        {
          key       = "${runtime}_snapshot_secret"
          secret_id = var.r2_snapshot_secret_access_key_secret_id
          member    = member
        }
      ]
      ]) : pair.key => {
      secret_id = pair.secret_id
      member    = pair.member
    }
  }
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each = merge(
    local.secret_bindings,
    local.optional_secret_bindings,
    local.snapshot_secret_bindings,
  )

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.member

  depends_on = [google_project_service.required]
}
