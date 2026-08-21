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
    deployment_mode: Literal["development", "local"] = "development"
    runtime_role: Literal["api", "worker", "migration", "initializer"] = "api"
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
    fpl_historical_base_url: str = (
        "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
    )
    fpl_current_base_url: str = "https://fantasy.premierleague.com"
    fpl_current_daily_request_limit: PositiveInt = 8
    fpl_current_operational_request_limit: PositiveInt = 4
    historical_data_base_url: str = "https://www.football-data.co.uk/mmz4281"
    raw_data_root: Path = Path("data/raw")
    processed_data_root: Path = Path("data/processed")
    goal_model_path: Path = Path("artifacts/models/goals/goals-v1-156511483a94/model.joblib")
    goal_model_sha256: str = "fe8a19c262b6a0d8aa02e01564f6c109eec2d16e237fa276e6a414967ecf0adc"
    statistics_model_path: Path = Path(
        "artifacts/models/match-statistics/detailed-statistics-v1-42e73adec486/model.joblib"
    )
    statistics_model_sha256: str = (
        "6859e2b0a6cd23382b795e68034b29548a6ac0a26fa9f08623cda5306cac4e12"
    )
    simulation_presentation_seconds: Literal[60] = 60

    @field_validator(
        "kickoff_api_key",
        "api_football_key",
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
        if self.deployment_mode == "local":
            if self.database_ssl_required:
                raise ValueError("local deployment must not require database SSL")
        if self.app_env.casefold() == "production" and not self.database_ssl_required:
            raise ValueError("DATABASE_SSL_REQUIRED must be true in production")
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
