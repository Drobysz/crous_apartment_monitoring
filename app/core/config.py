from functools import lru_cache

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    telegram_bot_token: SecretStr | None = None
    database_url: str = "postgresql+asyncpg://crous:crous@localhost:5432/crous"
    redis_url: str = "redis://localhost:6379/0"
    run_mode: str = "webhook"
    public_base_url: HttpUrl | None = None
    webhook_secret: SecretStr | None = None
    api_prefix: str = "/crous_bot_api"
    web_app_prefix: str = "/web_app"
    admin_panel_prefix: str = "/panel"
    telegram_webhook_path: str = "/telegram/webhook"
    stripe_webhook_path: str = "/stripe/webhook"
    payment_success_path: str = "/payments/success"
    payment_cancel_path: str = "/payments/cancel"
    nginx_internal_port: int = 80
    nginx_external_port: int = 8080
    crous_base_url: HttpUrl = HttpUrl("https://trouverunlogement.lescrous.fr")
    crous_locale: str = "fr"
    display_timezone: str = "Europe/Paris"
    max_search_area_degrees: float = 4.0
    max_image_bytes: int = 8 * 1024 * 1024
    monitoring_interval_seconds: int = 5 * 60
    free_monitoring_interval_seconds: int = 60 * 60
    premium_monitoring_interval_seconds: int = 2 * 60
    monitoring_lock_ttl_seconds: int = 2 * 60
    monitoring_max_retries: int = 3
    monitoring_retry_base_seconds: int = 15
    log_level: str = "INFO"
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    telegram_bot_url: HttpUrl | None = None
    test_mode: bool = False
    developer_telegram_ids: str = ""
    trial_duration_hours: int = 12
    season_start_month: int = 7
    season_start_day: int = 7
    season_end_month: int = 10
    season_end_day: int = 31
    enable_lifetime_plan: bool = True
    max_filter_price_euros: int = 10_000
    max_filter_surface_m2: float = 1_000

    def is_developer(self, telegram_user_id: int) -> bool:
        return self.test_mode and telegram_user_id in {
            int(value) for value in self.developer_telegram_ids.split(",") if value.strip().isdigit()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
