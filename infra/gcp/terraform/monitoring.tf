locals {
  runtime_log_metrics = {
    t24_missing = {
      display_name  = "T-24 forecast missing events"
      description   = "A scheduled exact fixture passed T-24 plus the configured grace period without a locked forecast."
      filter        = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.forecast.name}\" AND jsonPayload.event=\"t24_forecast_missing\""
      runbook       = "Check the task ledger, forecast service requests, job_runs, model artifacts, and player coverage."
      resource_type = "cloud_run_revision"
    }
    forecast_terminal = {
      display_name  = "Terminal forecast failures"
      description   = "A forecast exhausted its bounded retry allowance."
      filter        = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.forecast.name}\" AND jsonPayload.event=\"forecast_task_terminal_failure\""
      runbook       = "Inspect the safe error_code and task ledger, then follow the retry procedure."
      resource_type = "cloud_run_revision"
    }
    forecast_enqueue = {
      display_name  = "Forecast task enqueue failures"
      description   = "A current fixture revision could not be submitted to Cloud Tasks."
      filter        = "resource.type=\"cloud_run_job\" AND (resource.labels.job_name=\"${google_cloud_run_v2_job.fixtures.name}\" OR resource.labels.job_name=\"${google_cloud_run_v2_job.maintenance.name}\") AND jsonPayload.event=\"forecast_task_enqueue_failed\""
      runbook       = "Check queue IAM and Cloud Tasks availability; the pending ledger row will be retried without another provider request."
      resource_type = "cloud_run_job"
    }
    forecast_stale = {
      display_name  = "Stale forecast task deliveries"
      description   = "A rescheduled or otherwise obsolete fixture task was safely discarded."
      filter        = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.forecast.name}\" AND jsonPayload.event=\"forecast_task_stale\""
      runbook       = "Confirm a newer revision task exists; repeated stale deliveries indicate reconciliation or provider churn."
      resource_type = "cloud_run_revision"
    }
    snapshot_service_failure = {
      display_name  = "Forecast snapshot publication failures"
      description   = "The private forecast service could not publish a sanitized public snapshot."
      filter        = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.forecast.name}\" AND jsonPayload.event=\"snapshot_publication_failed\""
      runbook       = "Inspect R2 availability, snapshot write credentials, manifest integrity, and task retries."
      resource_type = "cloud_run_revision"
    }
    snapshot_job_failure = {
      display_name  = "Scheduled snapshot publication failures"
      description   = "Fixture synchronization or maintenance could not refresh public snapshots."
      filter        = "resource.type=\"cloud_run_job\" AND (resource.labels.job_name=\"${google_cloud_run_v2_job.fixtures.name}\" OR resource.labels.job_name=\"${google_cloud_run_v2_job.maintenance.name}\") AND jsonPayload.event=\"snapshot_publication_failed\""
      runbook       = "Inspect R2 availability, snapshot write credentials, manifest integrity, and the next reconciliation run."
      resource_type = "cloud_run_job"
    }
    storage_failure = {
      display_name  = "Raw response storage failures"
      description   = "A provider response could not be durably stored in R2."
      filter        = "resource.type=\"cloud_run_job\" AND (resource.labels.job_name=\"${google_cloud_run_v2_job.fixtures.name}\" OR resource.labels.job_name=\"${google_cloud_run_v2_job.players.name}\") AND jsonPayload.event=\"raw_response_storage_failed\""
      runbook       = "Stop provider ingestion until R2 access and durability are restored."
      resource_type = "cloud_run_job"
    }
    provider_quota = {
      display_name  = "Provider quota warning events"
      description   = "KickoffAPI usage reached the conservative warning threshold."
      filter        = "resource.type=\"cloud_run_job\" AND (resource.labels.job_name=\"${google_cloud_run_v2_job.fixtures.name}\" OR resource.labels.job_name=\"${google_cloud_run_v2_job.players.name}\" OR resource.labels.job_name=\"${google_cloud_run_v2_job.maintenance.name}\") AND jsonPayload.event=\"provider_quota_approaching\""
      runbook       = "Review today's provider ledger before manually invoking any ingestion job."
      resource_type = "cloud_run_job"
    }
    scheduler_failure = {
      display_name  = "Cloud Scheduler failures"
      description   = "A Prem Engine Scheduler trigger emitted an error."
      filter        = "resource.type=\"cloud_scheduler_job\" AND severity>=ERROR AND (resource.labels.job_id=\"${google_cloud_scheduler_job.jobs["maintenance"].name}\" OR resource.labels.job_id=\"${google_cloud_scheduler_job.jobs["fixtures"].name}\" OR resource.labels.job_id=\"${google_cloud_scheduler_job.jobs["players"].name}\")"
      runbook       = "Check Scheduler authentication, Cloud Run invoker IAM, and the target job execution."
      resource_type = "cloud_scheduler_job"
    }
  }

  monitored_jobs = {
    fixtures    = google_cloud_run_v2_job.fixtures.name
    players     = google_cloud_run_v2_job.players.name
    maintenance = google_cloud_run_v2_job.maintenance.name
    migration   = google_cloud_run_v2_job.migration.name
  }
}

resource "google_logging_metric" "runtime_events" {
  for_each = local.runtime_log_metrics

  project     = var.project_id
  name        = "${local.resource_name}-${replace(each.key, "_", "-")}"
  description = each.value.description
  filter      = each.value.filter

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = each.value.display_name
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "runtime_events" {
  for_each = local.runtime_log_metrics

  project               = var.project_id
  display_name          = "${local.resource_name}: ${each.value.display_name}"
  combiner              = "OR"
  enabled               = var.alerting_enabled
  notification_channels = var.notification_channel_ids

  documentation {
    content   = "${each.value.description}\n\n${each.value.runbook}\n\nSee docs/deployment/DEPLOYMENT_AND_MAINTENANCE.md."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = each.value.display_name
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.runtime_events[each.key].name}\" AND resource.type=\"${each.value.resource_type}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
      trigger {
        count = 1
      }
    }
  }
}

resource "google_monitoring_alert_policy" "api_5xx" {
  project               = var.project_id
  display_name          = "${local.resource_name}: API 5xx responses"
  combiner              = "OR"
  enabled               = var.alerting_enabled
  notification_channels = var.notification_channel_ids

  documentation {
    content   = "The API returned at least one 5xx response in a five-minute alignment window. Use X-Request-ID to correlate the request with structured application logs."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "API 5xx count"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
      trigger {
        count = 1
      }
    }
  }
}

resource "google_monitoring_alert_policy" "forecast_5xx" {
  project               = var.project_id
  display_name          = "${local.resource_name}: forecast task 5xx responses"
  combiner              = "OR"
  enabled               = var.alerting_enabled
  notification_channels = var.notification_channel_ids

  documentation {
    content   = "The private forecast handler returned a 5xx response. Cloud Tasks retries with bounded backoff; inspect the task ledger and safe error_code."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Forecast task 5xx count"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.forecast.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
      trigger { count = 1 }
    }
  }
}

resource "google_monitoring_alert_policy" "job_execution_failed" {
  for_each = local.monitored_jobs

  project               = var.project_id
  display_name          = "${local.resource_name}: ${each.key} job failed"
  combiner              = "OR"
  enabled               = var.alerting_enabled
  notification_channels = var.notification_channel_ids

  documentation {
    content   = "Cloud Run reported a failed ${each.key} execution. Inspect that execution's logs before retrying. Migration retries require a fresh backup and explicit operator approval."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Failed ${each.key} execution"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${each.value}\" AND metric.type=\"run.googleapis.com/job/completed_execution_count\" AND metric.labels.result=\"failed\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
      trigger {
        count = 1
      }
    }
  }
}

resource "google_monitoring_dashboard" "operations" {
  project = var.project_id
  dashboard_json = jsonencode({
    displayName = "${local.resource_name} operations"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          xPos   = 0
          yPos   = 0
          width  = 6
          height = 4
          widget = {
            title = "API requests by response class"
            xyChart = {
              dataSets = [{
                plotType = "LINE"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.type=\"run.googleapis.com/request_count\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.label.response_code_class"]
                    }
                  }
                }
              }]
              yAxis = { label = "requests/second", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 6
          yPos   = 0
          width  = 6
          height = 4
          widget = {
            title = "API p95 latency"
            xyChart = {
              dataSets = [{
                plotType = "LINE"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_PERCENTILE_95"
                    }
                  }
                }
              }]
              yAxis = { label = "latency", scale = "LINEAR" }
            }
          }
        },
        {
          xPos   = 0
          yPos   = 4
          width  = 12
          height = 4
          widget = {
            title = "Cloud Run job executions"
            xyChart = {
              dataSets = [{
                plotType = "STACKED_BAR"
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "resource.type=\"cloud_run_job\" AND metric.type=\"run.googleapis.com/job/completed_execution_count\""
                    aggregation = {
                      alignmentPeriod    = "300s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["resource.label.job_name", "metric.label.result"]
                    }
                  }
                }
              }]
              yAxis = { label = "executions", scale = "LINEAR" }
            }
          }
        }
      ]
    }
  })

  depends_on = [google_project_service.required]
}
