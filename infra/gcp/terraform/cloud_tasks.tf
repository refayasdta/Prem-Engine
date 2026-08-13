resource "google_cloud_tasks_queue" "forecast" {
  project  = var.project_id
  location = var.region
  name     = "${local.resource_name}-forecast"

  rate_limits {
    max_concurrent_dispatches = 1
    max_dispatches_per_second = 1
  }

  retry_config {
    max_attempts       = 4
    max_retry_duration = "3600s"
    min_backoff        = "60s"
    max_backoff        = "900s"
    max_doublings      = 3
  }

  stackdriver_logging_config {
    sampling_ratio = 1
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_tasks_queue_iam_member" "enqueuer" {
  for_each = {
    fixtures    = google_service_account.fixtures.member
    maintenance = google_service_account.maintenance.member
  }

  project  = var.project_id
  location = google_cloud_tasks_queue.forecast.location
  name     = google_cloud_tasks_queue.forecast.name
  role     = "roles/cloudtasks.enqueuer"
  member   = each.value
}

resource "google_service_account_iam_member" "task_creator_can_act_as_invoker" {
  for_each = {
    fixtures    = google_service_account.fixtures.member
    maintenance = google_service_account.maintenance.member
  }

  service_account_id = google_service_account.task_invoker.name
  role               = "roles/iam.serviceAccountUser"
  member             = each.value

  depends_on = [google_project_service.required]
}
