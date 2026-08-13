locals {
  scheduled_jobs = {
    fixtures = {
      schedule = "0 */4 * * *"
      job_name = google_cloud_run_v2_job.fixtures.name
    }
    players = {
      schedule = "15 2 * * *"
      job_name = google_cloud_run_v2_job.players.name
    }
    maintenance = {
      schedule = "30 3 * * *"
      job_name = google_cloud_run_v2_job.maintenance.name
    }
  }
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  for_each = local.scheduled_jobs

  project  = var.project_id
  location = var.region
  name     = each.value.job_name
  role     = "roles/run.invoker"
  member   = google_service_account.scheduler.member
}

resource "google_cloud_scheduler_job" "jobs" {
  for_each = local.scheduled_jobs

  project          = var.project_id
  region           = var.region
  name             = "${each.value.job_name}-schedule"
  description      = "Invoke ${each.value.job_name}; managed by Terraform"
  schedule         = each.value.schedule
  time_zone        = "Etc/UTC"
  paused           = var.scheduler_paused
  attempt_deadline = "320s"

  retry_config {
    retry_count          = 1
    min_backoff_duration = "30s"
    max_backoff_duration = "120s"
    max_doublings        = 2
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${each.value.job_name}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    google_cloud_run_v2_job_iam_member.scheduler_invoker,
    google_project_service.required,
  ]
}
