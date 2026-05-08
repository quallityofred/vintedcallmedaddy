# app/web/schemas.py
from pydantic import BaseModel, Field


class MonitorCreate(BaseModel):
    name: str
    url: str
    domains: list[str]
    interval_sec: int = 120


class MonitorUpdate(BaseModel):
    name: str
    url: str
    domains: list[str]
    interval_sec: int
    is_active: bool


class SettingsForm(BaseModel):
    telegram_token: str = ""
    telegram_chat_id: str = ""
    proxies: str = ""
    sessions_per_domain: int = 3
    rate_limit_per_minute: int = 8
