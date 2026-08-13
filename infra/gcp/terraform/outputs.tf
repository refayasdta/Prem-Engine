output "api_url" {
  description = "Cloud Run API URL to configure as Vercel PREM_ENGINE_API_BASE_URL."
  value       = google_cloud_run_v2_service.api.uri
}

output "artifact_repository" {
  description = "Artifact Registry repository used by the release workflow."
  value       = google_artifact_registry_repository.containers.name
}

output "scheduled_jobs" {
  description = "Scheduler resources and their safety state."
  value = {
    for key, job in google_cloud_scheduler_job.jobs : key => {
      name   = job.name
      paused = job.paused
    }
  }
}

output "migration_job" {
  description = "Unscheduled migration job; execute only after a verified backup."
  value       = google_cloud_run_v2_job.migration.name
}

output "forecast_task_queue" {
  description = "Cloud Tasks queue that owns exact T-24 delivery."
  value       = google_cloud_tasks_queue.forecast.name
}

output "forecast_service_url" {
  description = "Private forecast handler URL; do not expose through Vercel."
  value       = google_cloud_run_v2_service.forecast.uri
}
