# app/config.py
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    telegram_chat_id: int
    check_interval_seconds: int = 120
    database_url: str = "sqlite+aiosqlite:////data/app.db"
    proxies: str = ""
    sessions_per_domain: int = 3
    rate_limit_per_minute: int = 8
    cf_worker_url: str = ""
    cf_worker_block_threshold: int = 2
    cf_worker_recovery_minutes: int = 10
    peak_start_hour: int = 8
    peak_end_hour: int = 23
    offpeak_interval_multiplier: float = 2.5
    night_interval_multiplier: float = 5.0

    model_config = SettingsConfigDict(env_file=".env")

    def get_proxy_list(self) -> list[str]:
        return [proxy.strip() for proxy in self.proxies.split(",") if proxy.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
