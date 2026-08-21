"""Application configuration loaded exclusively from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import NonNegativeInt, PositiveInt, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings shared by the API and scheduled jobs."""

    app_env: str = "development"
    deployment_mode: Literal["development", "local", "hosted"] = "development"
    runtime_role: Literal["api", "worker", "forecast", "migration", "initializer"] = "api"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://prem_engine:prem_engine@127.0.0.1:55432/prem_engine"
    database_pool_size: PositiveInt = 5
    database_max_overflow: NonNegativeInt = 2
    database_pool_recycle_seconds: PositiveInt = 1800
    database_pool_timeout_seconds: PositiveInt = 10
    database_readiness_timeout_seconds: PositiveInt = 3
    database_ssl_required: bool = False
    local_fixture_freshness_seconds: PositiveInt = 14400
    local_worker_heartbeat_seconds: PositiveInt = 30
    local_fixture_sync_interval_seconds: PositiveInt = 14400
    local_full_fixture_sync_interval_seconds: PositiveInt = 86400
    local_fixture_sync_lookback_days: PositiveInt = 2
    local_fixture_sync_horizon_days: PositiveInt = 45
    local_fixture_sync_page_size: PositiveInt = 50
    local_fixture_sync_max_pages: PositiveInt = 20
    local_worker_lease_seconds: PositiveInt = 900
    local_worker_retry_seconds: PositiveInt = 300
    local_player_sync_interval_seconds: PositiveInt = 86400
    local_player_sync_max_requests: PositiveInt = 12
    local_player_sync_max_squads: NonNegativeInt = 6
    local_player_sync_max_matches: NonNegativeInt = 1
    local_goal_training_enabled: bool = True
    local_goal_training_retry_seconds: PositiveInt = 900
    local_model_root: Path = Path("artifacts/local")
    local_season_start_year: PositiveInt | None = None
    local_competition_code: str = "en.1"
    local_competition_name: str = "Premier League"
    kickoff_api_base_url: str = "https://api.kickoffapi.com"
    kickoff_api_key: SecretStr | None = None
    kickoff_daily_request_limit: int = 100
    kickoff_operational_request_limit: int = 85
    kickoff_operational_minute_limit: PositiveInt = 25
    kickoff_quota_warning_threshold: int = 80
    api_football_base_url: str = "https://v3.football.api-sports.io"
    api_football_key: SecretStr | None = None
    api_football_daily_request_limit: int = 100
    api_football_audit_request_limit: int = 24
    api_rate_limit_enabled: bool = True
    api_rate_limit_requests: PositiveInt = 300
    api_rate_limit_window_seconds: PositiveInt = 60
    api_origin_auth_enabled: bool = False
    api_origin_token: SecretStr | None = None
    api_origin_token_previous: SecretStr | None = None
    fpl_historical_base_url: str = (
        "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
    )
    fpl_current_base_url: str = "https://fantasy.premierleague.com"
    fpl_current_daily_request_limit: PositiveInt = 8
    fpl_current_operational_request_limit: PositiveInt = 4
    historical_data_base_url: str = "https://www.football-data.co.uk/mmz4281"
    raw_data_root: Path = Path("data/raw")
    raw_response_store: Literal["local", "r2"] = "local"
    r2_account_id: str | None = None
    r2_bucket_name: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_endpoint_url: str | None = None
    public_snapshot_store: Literal["disabled", "local", "r2"] = "disabled"
    public_snapshot_root: Path = Path("data/public-snapshots")
    public_snapshot_ttl_seconds: PositiveInt = 18000
    public_snapshot_default_cache_seconds: PositiveInt = 300
    public_snapshot_forecast_cache_seconds: PositiveInt = 30
    public_snapshot_horizon_days: Literal[30] = 30
    r2_snapshot_bucket_name: str | None = None
    r2_snapshot_access_key_id: str | None = None
    r2_snapshot_secret_access_key: SecretStr | None = None
    processed_data_root: Path = Path("data/processed")
    goal_model_path: Path = Path("artifacts/models/goals/goals-v1-156511483a94/model.joblib")
    goal_model_sha256: str = "fe8a19c262b6a0d8aa02e01564f6c109eec2d16e237fa276e6a414967ecf0adc"
    statistics_model_path: Path = Path(
        "artifacts/models/match-statistics/detailed-statistics-v1-42e73adec486/model.joblib"
    )
    statistics_model_sha256: str = (
        "6859e2b0a6cd23382b795e68034b29548a6ac0a26fa9f08623cda5306cac4e12"
    )
    forecast_dispatch_batch_size: PositiveInt = 10
    forecast_job_lease_seconds: PositiveInt = 300
    forecast_job_max_attempts: PositiveInt = 4
    forecast_retry_delay_seconds: PositiveInt = 300
    forecast_monitoring_grace_seconds: NonNegativeInt = 600
    simulation_presentation_seconds: Literal[60] = 60
    forecast_task_scheduling_enabled: bool = False
    cloud_tasks_project_id: str | None = None
    cloud_tasks_location: str | None = None
    forecast_task_queue_id: str | None = None
    forecast_task_target_url: str | None = None
    forecast_task_invoker_service_account: str | None = None
    forecast_task_dispatch_deadline_seconds: PositiveInt = 600
    forecast_task_horizon_days: Literal[30] = 30
    forecast_task_horizon_safety_seconds: PositiveInt = 300

    @field_validator(
        "kickoff_api_key",
        "api_football_key",
        "api_origin_token",
        "api_origin_token_previous",
        "r2_secret_access_key",
        "r2_snapshot_secret_access_key",
        mode="before",
    )
    @classmethod
    def empty_secret_is_unset(cls, value: object) -> object:
        """Treat empty optional secret-store values as absent."""

        return None if value == "" else value

    @field_validator("local_season_start_year", mode="before")
    @classmethod
    def empty_optional_integer_is_unset(cls, value: object) -> object:
        """Allow an empty Compose override to request automatic season inference."""

        return None if value == "" else value

    @model_validator(mode="after")
    def validate_operational_safety(self) -> Settings:
        """Prevent environment overrides from exceeding provider and production safeguards."""

        if self.kickoff_daily_request_limit > 100:
            raise ValueError("KICKOFF_DAILY_REQUEST_LIMIT cannot exceed KickoffAPI's 100/day limit")
        if self.kickoff_operational_request_limit > 85:
            raise ValueError("KICKOFF_OPERATIONAL_REQUEST_LIMIT cannot exceed 85/day")
        if self.kickoff_operational_request_limit > self.kickoff_daily_request_limit:
            raise ValueError("KickoffAPI operational limit cannot exceed its daily hard limit")
        if self.kickoff_operational_minute_limit > 25:
            raise ValueError("KICKOFF_OPERATIONAL_MINUTE_LIMIT cannot exceed 25/minute")
        if self.local_fixture_sync_page_size > 50:
            raise ValueError("LOCAL_FIXTURE_SYNC_PAGE_SIZE cannot exceed 50")
        if self.local_fixture_sync_max_pages > 20:
            raise ValueError("LOCAL_FIXTURE_SYNC_MAX_PAGES cannot exceed 20")
        if self.local_player_sync_max_requests > self.kickoff_operational_request_limit:
            raise ValueError("local player sync must fit inside the operational daily allowance")
        if self.fpl_current_operational_request_limit > self.fpl_current_daily_request_limit:
            raise ValueError("FPL current operational limit cannot exceed its daily hard limit")
        if not 1 <= self.kickoff_quota_warning_threshold <= 85:
            raise ValueError("KICKOFF_QUOTA_WARNING_THRESHOLD must be between 1 and 85")
        if self.api_origin_auth_enabled and self.api_origin_token is None:
            raise ValueError("API_ORIGIN_TOKEN is required when origin authentication is enabled")
        if self.api_origin_auth_enabled:
            origin_tokens = (self.api_origin_token, self.api_origin_token_previous)
            if any(
                token is not None and len(token.get_secret_value().encode()) < 32
                for token in origin_tokens
            ):
                raise ValueError("origin tokens must contain at least 32 bytes")
        if self.deployment_mode == "local":
            if self.database_ssl_required:
                raise ValueError("local deployment must not require database SSL")
            if self.forecast_task_scheduling_enabled:
                raise ValueError("local deployment cannot enable Cloud Tasks scheduling")
            if self.public_snapshot_store != "disabled":
                raise ValueError("local deployment cannot publish hosted public snapshots")
        if self.app_env.casefold() == "production" and not self.database_ssl_required:
            raise ValueError("DATABASE_SSL_REQUIRED must be true in production")
        if (
            self.app_env.casefold() == "production"
            and self.runtime_role == "api"
            and not self.api_origin_auth_enabled
        ):
            raise ValueError("API_ORIGIN_AUTH_ENABLED must be true in production")
        if self.forecast_task_dispatch_deadline_seconds > 1800:
            raise ValueError("FORECAST_TASK_DISPATCH_DEADLINE_SECONDS cannot exceed 1800")
        if self.forecast_monitoring_grace_seconds < self.simulation_presentation_seconds:
            raise ValueError("FORECAST_MONITORING_GRACE_SECONDS cannot end before the reveal")
        if self.forecast_task_horizon_safety_seconds >= 86400:
            raise ValueError("FORECAST_TASK_HORIZON_SAFETY_SECONDS must be less than one day")
        task_fields = {
            "CLOUD_TASKS_PROJECT_ID": self.cloud_tasks_project_id,
            "CLOUD_TASKS_LOCATION": self.cloud_tasks_location,
            "FORECAST_TASK_QUEUE_ID": self.forecast_task_queue_id,
            "FORECAST_TASK_TARGET_URL": self.forecast_task_target_url,
            "FORECAST_TASK_INVOKER_SERVICE_ACCOUNT": (self.forecast_task_invoker_service_account),
        }
        if self.forecast_task_scheduling_enabled:
            missing = [name for name, value in task_fields.items() if not value]
            if missing:
                raise ValueError(f"Cloud Tasks scheduling is missing {', '.join(missing)}")
        if self.app_env.casefold() == "production" and self.runtime_role == "forecast":
            if not self.forecast_task_queue_id:
                raise ValueError("forecast runtime is missing FORECAST_TASK_QUEUE_ID")
        if self.forecast_task_target_url:
            from urllib.parse import urlsplit

            target = urlsplit(self.forecast_task_target_url)
            if (
                (self.app_env.casefold() == "production" and target.scheme != "https")
                or not target.netloc
                or target.username is not None
                or target.password is not None
                or bool(target.query)
                or bool(target.fragment)
            ):
                raise ValueError("FORECAST_TASK_TARGET_URL must be a safe absolute URL")
        if self.public_snapshot_default_cache_seconds > self.public_snapshot_ttl_seconds:
            raise ValueError("snapshot cache duration cannot exceed snapshot freshness duration")
        if self.public_snapshot_default_cache_seconds > 300:
            raise ValueError("default snapshot cache duration cannot exceed 300 seconds")
        if self.public_snapshot_forecast_cache_seconds > 60:
            raise ValueError("forecast snapshot cache duration cannot exceed 60 seconds")
        if self.public_snapshot_store == "local" and self.app_env.casefold() == "production":
            raise ValueError("production public snapshot storage cannot use the local filesystem")
        if self.public_snapshot_store == "r2":
            snapshot_fields = {
                "R2_ACCOUNT_ID": self.r2_account_id,
                "R2_SNAPSHOT_BUCKET_NAME": self.r2_snapshot_bucket_name,
                "R2_SNAPSHOT_ACCESS_KEY_ID": self.r2_snapshot_access_key_id,
                "R2_SNAPSHOT_SECRET_ACCESS_KEY": (
                    self.r2_snapshot_secret_access_key.get_secret_value()
                    if self.r2_snapshot_secret_access_key is not None
                    else None
                ),
            }
            missing = [name for name, value in snapshot_fields.items() if not value]
            if missing:
                raise ValueError(f"R2 public snapshot storage is missing {', '.join(missing)}")
            if self.r2_bucket_name and self.r2_snapshot_bucket_name == self.r2_bucket_name:
                raise ValueError("R2 public snapshots must use a separate bucket from raw captures")
            if self.r2_access_key_id and self.r2_snapshot_access_key_id == self.r2_access_key_id:
                raise ValueError(
                    "R2 public snapshots must use a separate credential from raw captures"
                )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings object per process."""

    return Settings()
