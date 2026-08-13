variable "project_id" {
  description = "Google Cloud project that owns the runtime resources."
  type        = string
}

variable "region" {
  description = "Single Cloud Run and Cloud Scheduler region."
  type        = string
  default     = "asia-southeast1"
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "staging"

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
  default     = "prem-engine"
}

variable "api_image" {
  description = "Immutable API Artifact Registry image reference, including @sha256 digest."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.api_image))
    error_message = "api_image must be pinned by a sha256 digest."
  }
}

variable "job_image" {
  description = "Immutable worker Artifact Registry image reference, including @sha256 digest."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.job_image))
    error_message = "job_image must be pinned by a sha256 digest."
  }
}

variable "season_start_year" {
  description = "Current Premier League season start year used by ingestion jobs."
  type        = number

  validation {
    condition     = var.season_start_year >= 2020 && var.season_start_year <= 2100
    error_message = "season_start_year must be a four-digit year between 2020 and 2100."
  }
}

variable "database_api_secret_id" {
  description = "Existing Secret Manager secret containing the API role DATABASE_URL."
  type        = string
}

variable "database_worker_secret_id" {
  description = "Existing Secret Manager secret containing the worker role DATABASE_URL."
  type        = string
}

variable "database_migration_secret_id" {
  description = "Existing Secret Manager secret containing the migration role DATABASE_URL."
  type        = string
}

variable "kickoff_api_key_secret_id" {
  description = "Existing Secret Manager secret containing KICKOFF_API_KEY."
  type        = string
}

variable "origin_token_secret_id" {
  description = "Existing Secret Manager secret containing API_ORIGIN_TOKEN."
  type        = string
}

variable "origin_previous_token_secret_id" {
  description = "Optional previous origin token used only during rotation."
  type        = string
  default     = null
  nullable    = true
}

variable "r2_access_key_id_secret_id" {
  description = "Existing Secret Manager secret containing R2_ACCESS_KEY_ID."
  type        = string
}

variable "r2_secret_access_key_secret_id" {
  description = "Existing Secret Manager secret containing R2_SECRET_ACCESS_KEY."
  type        = string
}

variable "r2_account_id" {
  description = "Cloudflare R2 account identifier (non-secret)."
  type        = string
}

variable "r2_bucket_name" {
  description = "Cloudflare R2 raw-response bucket name."
  type        = string
}

variable "r2_endpoint_url" {
  description = "Optional R2 endpoint override."
  type        = string
  default     = null
  nullable    = true
}

variable "public_snapshot_enabled" {
  description = "Safety gate: publish sanitized public read snapshots to a separate R2 bucket."
  type        = bool
  default     = false
}

variable "r2_snapshot_bucket_name" {
  description = "Separate Cloudflare R2 bucket for sanitized public snapshots."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = !var.public_snapshot_enabled || try(length(trimspace(var.r2_snapshot_bucket_name)) > 0, false)
    error_message = "r2_snapshot_bucket_name is required when public snapshots are enabled."
  }
}

variable "r2_snapshot_access_key_id_secret_id" {
  description = "Secret containing the write-only public snapshot R2 access key ID."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = !var.public_snapshot_enabled || try(length(trimspace(var.r2_snapshot_access_key_id_secret_id)) > 0, false)
    error_message = "r2_snapshot_access_key_id_secret_id is required when public snapshots are enabled."
  }
}

variable "r2_snapshot_secret_access_key_secret_id" {
  description = "Secret containing the write-only public snapshot R2 secret access key."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = !var.public_snapshot_enabled || try(length(trimspace(var.r2_snapshot_secret_access_key_secret_id)) > 0, false)
    error_message = "r2_snapshot_secret_access_key_secret_id is required when public snapshots are enabled."
  }
}

variable "scheduler_paused" {
  description = "Safety gate: scheduled invocations stay paused until staging acceptance is signed off."
  type        = bool
  default     = true
}

variable "forecast_task_scheduling_enabled" {
  description = "Safety gate: permit fixture and maintenance jobs to create exact T-24 tasks."
  type        = bool
  default     = false
}

variable "deletion_protection" {
  description = "Protect Cloud Run resources from accidental Terraform deletion."
  type        = bool
  default     = true
}

variable "alerting_enabled" {
  description = "Enable alert policy evaluation after notification routing is verified."
  type        = bool
  default     = false
}

variable "notification_channel_ids" {
  description = "Existing Cloud Monitoring notification-channel resource IDs."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for channel in var.notification_channel_ids : length(trimspace(channel)) > 0])
    error_message = "notification_channel_ids cannot contain empty values."
  }
}
