# app/config.py
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
telegram_bot_token: str = ""
telegram_chat_id: int = 0
check_interval_seconds: int = 120
secret_key: str = ""  # MUST be set in .env for production!
database_url: str = "postgresql+asyncpg://postgres:password@localhost/vintedbot?ssl=require"

@property
def database_url_validated(self) -> str:
url = self.database_url

if url.startswith("postgresql://"):
url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

cloud_domains = ["[supabase.co](https://supabase.co)", "[supabase.com](https://supabase.com)", "[neon.tech](https://neon.tech)", "railway.app"]
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
if not db_[path.is](https://path.is)_absolute():
db_path = Path.cwd() / db_path
return db_path.parent

@lru_cache(maxsize=1)
def get_settings() -> Settings:
settings = Settings()

if not settings.secret_key or settings.secret_key == "change-me-in-production":
import os
if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER"):
raise ValueError(
"SECRET_KEY must be set in .env file for production deployment!\n"
"Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
)

return settings