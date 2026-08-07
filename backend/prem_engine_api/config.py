"""Application configuration loaded exclusively from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
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
    historical_data_base_url: str = "https://www.football-data.co.uk/mmz4281"
    raw_data_root: Path = Path("data/raw")
    processed_data_root: Path = Path("data/processed")

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
