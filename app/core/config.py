from functools import lru_cache

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    telegram_bot_token: SecretStr | None = None
    database_url: str = "postgresql+asyncpg://crous:crous@localhost:5432/crous"
    redis_url: str = "redis://localhost:6379/0"
    run_mode: str = "polling"
    webhook_base_url: HttpUrl | None = None
    webhook_secret: SecretStr | None = None
    crous_base_url: HttpUrl = HttpUrl("https://trouverunlogement.lescrous.fr")
    crous_locale: str = "fr"
    display_timezone: str = "Europe/Paris"
    max_search_area_degrees: float = 4.0
    max_image_bytes: int = 8 * 1024 * 1024
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
