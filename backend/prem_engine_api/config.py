"""Application configuration loaded exclusively from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings shared by the API and scheduled jobs."""

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://prem_engine:prem_engine@127.0.0.1:55432/prem_engine"
    kickoff_api_base_url: str = "https://api.kickoffapi.com"
    kickoff_api_key: SecretStr | None = None
    kickoff_daily_request_limit: int = 100
    kickoff_operational_request_limit: int = 85
    kickoff_operational_minute_limit: PositiveInt = 25
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
    forecast_dispatch_batch_size: PositiveInt = 10
    forecast_job_lease_seconds: PositiveInt = 300
    forecast_job_max_attempts: PositiveInt = 4
    forecast_retry_delay_seconds: PositiveInt = 300
    simulation_presentation_seconds: Literal[60] = 60

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
