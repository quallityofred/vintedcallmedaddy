# app/config.py
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    telegram_chat_id: int = 0
    check_interval_seconds: int = 120
    secret_key: str = "change-me-in-production"
    database_url: str = "sqlite+aiosqlite:///./data/vinted.db"
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

    def get_sqlite_data_dir(self) -> Path | None:
        prefix = "sqlite+aiosqlite:///"
        if not self.database_url.startswith(prefix):
            return None
        raw_path = self.database_url[len(prefix):]
        if ":memory:" in raw_path:
            return None
        db_path = Path(raw_path)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        return db_path.parent


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
