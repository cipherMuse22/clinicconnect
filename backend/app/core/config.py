from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://clinic:clinic_dev_pw@localhost:5432/clinicconnect"
    secret_key: str = "change-me-use-a-long-random-string"
    access_token_minutes: int = 30
    privacy_notice_version: str = "2026-11-v1"
    cors_origins: list[str] = ["http://localhost:5173"]
        # Development convenience: allow any localhost port (Flutter web picks a random one). Set to "" in production.
    cors_origin_regex: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
    clinic_timezone: str = "Africa/Johannesburg"
    cancellation_cutoff_hours: int = 2  # patients cannot cancel or reschedule closer than this
    notification_channels: list[str] = ["in_app"]  # add "sms" and/or "email" once real providers exist
    reminder_hours_before: int = 24
    scheduler_enabled: bool = True
    scheduler_interval_minutes: int = 15
    checkin_window_minutes: int = 60  # patients may check in this long before the slot starts
    checkin_grace_minutes: int = 30  # ...and up to this long after it ends


@lru_cache
def get_settings() -> Settings:
    return Settings()
