resource "google_cloud_run_v2_service" "api" {
  project             = var.project_id
  name                = "${local.resource_name}-api"
  location            = var.region
  deletion_protection = var.deletion_protection
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = local.common_labels

  template {
    service_account                  = google_service_account.api.email
    timeout                          = "30s"
    max_instance_request_concurrency = 20

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = var.api_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "APP_ENV"
        value = var.environment
      }
      env {
        name  = "RUNTIME_ROLE"
        value = "api"
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "DATABASE_SSL_REQUIRED"
        value = "true"
      }
      env {
        name  = "DATABASE_POOL_SIZE"
        value = "5"
      }
      env {
        name  = "DATABASE_MAX_OVERFLOW"
        value = "2"
      }
      env {
        name  = "API_ORIGIN_AUTH_ENABLED"
        value = "true"
      }
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = var.database_api_secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "API_ORIGIN_TOKEN"
        value_source {
          secret_key_ref {
            secret  = var.origin_token_secret_id
            version = "latest"
          }
        }
      }
      dynamic "env" {
        for_each = var.origin_previous_token_secret_id == null ? [] : [var.origin_previous_token_secret_id]
        content {
          name = "API_ORIGIN_TOKEN_PREVIOUS"
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 12
        http_get {
          path = "/ready"
          port = 8080
        }
      }

      liveness_probe {
        initial_delay_seconds = 10
        timeout_seconds       = 3
        period_seconds        = 30
        failure_threshold     = 3
        http_get {
          path = "/health"
          port = 8080
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.runtime,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public_api" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "forecast" {
  project             = var.project_id
  name                = "${local.resource_name}-forecast"
  location            = var.region
  deletion_protection = var.deletion_protection
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = local.common_labels

  template {
    service_account                  = google_service_account.forecast.email
    timeout                          = "600s"
    max_instance_request_concurrency = 1
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image   = var.job_image
      command = ["uvicorn"]
      args    = ["prem_engine_api.forecast_task_app:app", "--host", "0.0.0.0", "--port", "8080"]
      ports { container_port = 8080 }
      resources {
        limits            = { cpu = "1", memory = "1Gi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      env {
        name  = "APP_ENV"
        value = var.environment
      }
      env {
        name  = "RUNTIME_ROLE"
        value = "forecast"
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
      env {
        name  = "DATABASE_SSL_REQUIRED"
        value = "true"
      }
      env {
        name  = "FORECAST_TASK_QUEUE_ID"
        value = google_cloud_tasks_queue.forecast.name
      }
      env {
        name  = "PUBLIC_SNAPSHOT_STORE"
        value = var.public_snapshot_enabled ? "r2" : "disabled"
      }
      dynamic "env" {
        for_each = var.public_snapshot_enabled ? [1] : []
        content {
          name  = "R2_ACCOUNT_ID"
          value = var.r2_account_id
        }
      }
      dynamic "env" {
        for_each = var.public_snapshot_enabled ? [1] : []
        content {
          name  = "R2_ENDPOINT_URL"
          value = local.r2_endpoint_url
        }
      }
      dynamic "env" {
        for_each = var.public_snapshot_enabled ? [1] : []
        content {
          name  = "R2_SNAPSHOT_BUCKET_NAME"
          value = var.r2_snapshot_bucket_name
        }
      }
      dynamic "env" {
        for_each = var.public_snapshot_enabled ? [1] : []
        content {
          name = "R2_SNAPSHOT_ACCESS_KEY_ID"
          value_source {
            secret_key_ref {
              secret  = var.r2_snapshot_access_key_id_secret_id
              version = "latest"
            }
          }
        }
      }
      dynamic "env" {
        for_each = var.public_snapshot_enabled ? [1] : []
        content {
          name = "R2_SNAPSHOT_SECRET_ACCESS_KEY"
          value_source {
            secret_key_ref {
              secret  = var.r2_snapshot_secret_access_key_secret_id
              version = "latest"
            }
          }
        }
      }
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = var.database_worker_secret_id
            version = "latest"
          }
        }
      }
      startup_probe {
        timeout_seconds   = 3
        period_seconds    = 10
        failure_threshold = 12
        http_get {
          path = "/ready"
          port = 8080
        }
      }
      liveness_probe {
        initial_delay_seconds = 10
        timeout_seconds       = 3
        period_seconds        = 30
        failure_threshold     = 3
        http_get {
          path = "/health"
          port = 8080
        }
      }
    }
  }

  depends_on = [
    google_cloud_tasks_queue.forecast,
    google_secret_manager_secret_iam_member.runtime,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "forecast_task_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.forecast.location
  name     = google_cloud_run_v2_service.forecast.name
  role     = "roles/run.invoker"
  member   = google_service_account.task_invoker.member
}

resource "google_cloud_run_v2_job" "fixtures" {
  project             = var.project_id
  name                = "${local.resource_name}-fixtures"
  location            = var.region
  deletion_protection = var.deletion_protection
  labels              = local.common_labels

  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = google_service_account.fixtures.email
      timeout         = "900s"
      max_retries     = 1
      containers {
        image   = var.job_image
        command = ["python"]
        args = [
          "backend/scripts/import_kickoffapi_season.py",
          "--league", "en.1",
          "--season", tostring(var.season_start_year),
          "--page-size", "50",
          "--max-pages", "10",
        ]
        resources { limits = { cpu = "1", memory = "1Gi" } }
        env {
          name  = "APP_ENV"
          value = var.environment
        }
        env {
          name  = "RUNTIME_ROLE"
          value = "worker"
        }
        env {
          name  = "LOG_LEVEL"
          value = "INFO"
        }
        env {
          name  = "DATABASE_SSL_REQUIRED"
          value = "true"
        }
        env {
          name  = "FORECAST_TASK_SCHEDULING_ENABLED"
          value = tostring(var.forecast_task_scheduling_enabled)
        }
        env {
          name  = "CLOUD_TASKS_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "CLOUD_TASKS_LOCATION"
          value = var.region
        }
        env {
          name  = "FORECAST_TASK_QUEUE_ID"
          value = google_cloud_tasks_queue.forecast.name
        }
        env {
          name  = "FORECAST_TASK_TARGET_URL"
          value = "${google_cloud_run_v2_service.forecast.uri}/tasks/forecast"
        }
        env {
          name  = "FORECAST_TASK_INVOKER_SERVICE_ACCOUNT"
          value = google_service_account.task_invoker.email
        }
        env {
          name  = "RAW_RESPONSE_STORE"
          value = "r2"
        }
        env {
          name  = "R2_ACCOUNT_ID"
          value = var.r2_account_id
        }
        env {
          name  = "R2_BUCKET_NAME"
          value = var.r2_bucket_name
        }
        env {
          name  = "R2_ENDPOINT_URL"
          value = local.r2_endpoint_url
        }
        env {
          name  = "PUBLIC_SNAPSHOT_STORE"
          value = var.public_snapshot_enabled ? "r2" : "disabled"
        }
        dynamic "env" {
          for_each = var.public_snapshot_enabled ? [1] : []
          content {
            name  = "R2_SNAPSHOT_BUCKET_NAME"
            value = var.r2_snapshot_bucket_name
          }
        }
        dynamic "env" {
          for_each = var.public_snapshot_enabled ? [1] : []
          content {
            name = "R2_SNAPSHOT_ACCESS_KEY_ID"
            value_source {
              secret_key_ref {
                secret  = var.r2_snapshot_access_key_id_secret_id
                version = "latest"
              }
            }
          }
        }
        dynamic "env" {
          for_each = var.public_snapshot_enabled ? [1] : []
          content {
            name = "R2_SNAPSHOT_SECRET_ACCESS_KEY"
            value_source {
              secret_key_ref {
                secret  = var.r2_snapshot_secret_access_key_secret_id
                version = "latest"
              }
            }
          }
        }
        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = var.database_worker_secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "KICKOFF_API_KEY"
          value_source {
            secret_key_ref {
              secret  = var.kickoff_api_key_secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "R2_ACCESS_KEY_ID"
          value_source {
            secret_key_ref {
              secret  = var.r2_access_key_id_secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "R2_SECRET_ACCESS_KEY"
          value_source {
            secret_key_ref {
              secret  = var.r2_secret_access_key_secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_cloud_tasks_queue_iam_member.enqueuer,
    google_secret_manager_secret_iam_member.runtime,
    google_service_account_iam_member.task_creator_can_act_as_invoker,
  ]
}

resource "google_cloud_run_v2_job" "maintenance" {
  project             = var.project_id
  name                = "${local.resource_name}-maintenance"
  location            = var.region
  deletion_protection = var.deletion_protection
  labels              = local.common_labels

  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = google_service_account.maintenance.email
      timeout         = "600s"
      max_retries     = 1
      containers {
        image   = var.job_image
        command = ["python"]
        args    = ["backend/scripts/run_maintenance.py"]
        resources { limits = { cpu = "1", memory = "512Mi" } }
        env {
          name  = "APP_ENV"
          value = var.environment
        }
        env {
          name  = "RUNTIME_ROLE"
          value = "worker"
        }
        env {
          name  = "LOG_LEVEL"
          value = "INFO"
        }
        env {
          name  = "DATABASE_SSL_REQUIRED"
          value = "true"
        }
        env {
          name  = "FORECAST_TASK_SCHEDULING_ENABLED"
          value = tostring(var.forecast_task_scheduling_enabled)
        }
        env {
          name  = "CLOUD_TASKS_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "CLOUD_TASKS_LOCATION"
          value = var.region
        }
        env {
          name  = "FORECAST_TASK_QUEUE_ID"
          value = google_cloud_tasks_queue.forecast.name
        }
        env {
          name  = "FORECAST_TASK_TARGET_URL"
          value = "${google_cloud_run_v2_service.forecast.uri}/tasks/forecast"
        }
        env {
          name  = "FORECAST_TASK_INVOKER_SERVICE_ACCOUNT"
          value = google_service_account.task_invoker.email
        }
        env {
          name  = "PUBLIC_SNAPSHOT_STORE"
          value = var.public_snapshot_enabled ? "r2" : "disabled"
        }
        dynamic "env" {
          for_each = var.public_snapshot_enabled ? [1] : []
          content {
            name  = "R2_ACCOUNT_ID"
            value = var.r2_account_id
          }
        }
        dynamic "env" {
          for_each = var.public_snapshot_enabled ? [1] : []
          content {
            name  = "R2_ENDPOINT_URL"
            value = local.r2_endpoint_url
          }
        }
        dynamic "env" {
          for_each = var.public_snapshot_enabled ? [1] : []
          content {
            name  = "R2_SNAPSHOT_BUCKET_NAME"
            value = var.r2_snapshot_bucket_name
          }
        }
        dynamic "env" {
          for_each = var.public_snapshot_enabled ? [1] : []
          content {
            name = "R2_SNAPSHOT_ACCESS_KEY_ID"
            value_source {
              secret_key_ref {
                secret  = var.r2_snapshot_access_key_id_secret_id
                version = "latest"
              }
            }
          }
        }
        dynamic "env" {
          for_each = var.public_snapshot_enabled ? [1] : []
          content {
            name = "R2_SNAPSHOT_SECRET_ACCESS_KEY"
            value_source {
              secret_key_ref {
                secret  = var.r2_snapshot_secret_access_key_secret_id
                version = "latest"
              }
            }
          }
        }
        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = var.database_worker_secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_cloud_tasks_queue_iam_member.enqueuer,
    google_secret_manager_secret_iam_member.runtime,
    google_service_account_iam_member.task_creator_can_act_as_invoker,
  ]
}

resource "google_cloud_run_v2_job" "players" {
  project             = var.project_id
  name                = "${local.resource_name}-players"
  location            = var.region
  deletion_protection = var.deletion_protection
  labels              = local.common_labels

  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = google_service_account.players.email
      timeout         = "900s"
      max_retries     = 1
      containers {
        image   = var.job_image
        command = ["python"]
        args = [
          "backend/scripts/sync_player_context.py",
          "--league", "en.1",
          "--season", tostring(var.season_start_year),
          "--max-requests", "16",
          "--max-squads", "10",
          "--max-matches", "2",
        ]
        resources { limits = { cpu = "1", memory = "1Gi" } }
        env {
          name  = "APP_ENV"
          value = var.environment
        }
        env {
          name  = "RUNTIME_ROLE"
          value = "worker"
        }
        env {
          name  = "LOG_LEVEL"
          value = "INFO"
        }
        env {
          name  = "DATABASE_SSL_REQUIRED"
          value = "true"
        }
        env {
          name  = "RAW_RESPONSE_STORE"
          value = "r2"
        }
        env {
          name  = "R2_ACCOUNT_ID"
          value = var.r2_account_id
        }
        env {
          name  = "R2_BUCKET_NAME"
          value = var.r2_bucket_name
        }
        env {
          name  = "R2_ENDPOINT_URL"
          value = local.r2_endpoint_url
        }
        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = var.database_worker_secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "KICKOFF_API_KEY"
          value_source {
            secret_key_ref {
              secret  = var.kickoff_api_key_secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "R2_ACCESS_KEY_ID"
          value_source {
            secret_key_ref {
              secret  = var.r2_access_key_id_secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "R2_SECRET_ACCESS_KEY"
          value_source {
            secret_key_ref {
              secret  = var.r2_secret_access_key_secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.runtime]
}

resource "google_cloud_run_v2_job" "migration" {
  project             = var.project_id
  name                = "${local.resource_name}-migration"
  location            = var.region
  deletion_protection = var.deletion_protection
  labels              = local.common_labels

  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = google_service_account.migration.email
      timeout         = "900s"
      max_retries     = 0
      containers {
        image   = var.job_image
        command = ["alembic"]
        args    = ["upgrade", "head"]
        resources { limits = { cpu = "1", memory = "512Mi" } }
        env {
          name  = "APP_ENV"
          value = var.environment
        }
        env {
          name  = "RUNTIME_ROLE"
          value = "migration"
        }
        env {
          name  = "DATABASE_SSL_REQUIRED"
          value = "true"
        }
        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = var.database_migration_secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.runtime]
}
