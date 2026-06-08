# app/config.py
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    telegram_chat_id: int | None = None
    environment: str = "development"
    frontend_url: str = ""
    allowed_origins: str = "*"
    check_interval_seconds: int = 120
    secret_key: str = ""  # MUST be set in .env for production!
    session_cookie_secure: bool = False
    database_url: str = "sqlite+aiosqlite:///:memory:"
    db_pool_size: int = 3
    db_max_overflow: int = 0
    db_pool_timeout: int = 10
    db_pool_recycle_seconds: int = 120
    db_connect_timeout_seconds: int = 10
    db_operation_timeout_seconds: int = 10
    db_use_null_pool: bool = False
    startup_db_timeout_seconds: int = 45
    startup_db_max_attempts: int = 3
    startup_db_retry_interval_seconds: int = 10
    startup_optional_timeout_seconds: int = 20
    auth_db_operation_timeout_seconds: int = 25
    monitor_check_global_concurrency: int = Field(default=2, ge=1)
    monitor_check_per_user_concurrency: int = Field(default=1, ge=1)
    monitor_check_acquire_timeout_seconds: float = Field(default=2.0, ge=0)
    monitor_check_max_pages_per_domain: int = Field(default=1, ge=1)
    monitor_candidate_detail_max_per_check: int = Field(default=10, ge=0)
    monitor_freshness_grace_seconds: int = Field(default=600, ge=0)
    monitor_detail_guard_enabled: bool = False
    monitor_detail_category_guard_enabled: bool = False
    monitor_detail_freshness_guard_enabled: bool = False
    monitor_hydration_source_enabled: bool = False
    monitor_ssr_photo_merge_enabled: bool = False
    scraper_engine_v2_enabled: bool = False
    pending_notifications_worker_enabled: bool = False
    notification_pipeline_v2_enabled: bool = False
    scraper_global_http_concurrency: int = Field(default=8, ge=1)
    scraper_domain_http_concurrency: int = Field(default=1, ge=1)
    scraper_domain_cooldown_seconds: int = Field(default=300, ge=0)

    @property
    def database_url_validated(self) -> str:
        url = self.database_url

        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)

        cloud_domains = ["supabase.co", "supabase.com", "neon.tech", "railway.app"]
        if any(cloud in url for cloud in cloud_domains):
            if "?ssl=" not in url:
                if "?" in url:
                    url += "&ssl=require"
                else:
                    url += "?ssl=require"
            elif "ssl=disable" in url:
                url = url.replace("ssl=disable", "ssl=require")
        return url

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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def get_proxy_list(self) -> list[str]:
        return [proxy.strip() for proxy in self.proxies.split(",") if proxy.strip()]

    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

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
    settings = Settings()

    if not settings.secret_key or settings.secret_key == "change-me-in-production":
        import os
        if (
            settings.environment.lower() in {"production", "prod"}
            or os.getenv("RAILWAY_ENVIRONMENT")
            or os.getenv("RENDER")
        ):
            raise ValueError(
                "SECRET_KEY must be set in .env file for production deployment!\n"
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )

    return settings
