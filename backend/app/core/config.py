from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://clinic:clinic_dev_pw@localhost:5432/clinicconnect"
    secret_key: str = "change-me-use-a-long-random-string"
    access_token_minutes: int = 30
    privacy_notice_version: str = "2026-11-v1"
    cors_origins: list[str] = ["http://localhost:5173"]
    clinic_timezone: str = "Africa/Johannesburg"
    cancellation_cutoff_hours: int = 2  # patients cannot cancel or reschedule closer than this


@lru_cache
def get_settings() -> Settings:
    return Settings()
