# app/models.py
import hashlib
import os
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    password_salt: Mapped[str] = mapped_column(String, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    telegram_bot_token: Mapped[str] = mapped_column(String, default="", nullable=False)
    telegram_chat_id: Mapped[str] = mapped_column(String, default="", nullable=False)
    invite_code_id: Mapped[int | None] = mapped_column(ForeignKey("invite_codes.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_salt = os.urandom(32).hex()
        self.password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(self.password_salt), 100_000
        ).hex()

    def check_password(self, password: str) -> bool:
        h = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(self.password_salt), 100_000
        ).hex()
        return h == self.password_hash


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_valid(self) -> bool:
        if not self.is_active:
            return False
        if self.used_count >= self.max_uses:
            return False
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return False
        return True


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_token", "token"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    original_url: Mapped[str] = mapped_column(String, nullable=False)
    params_json: Mapped[str] = mapped_column(String, nullable=False)
    domains_json: Mapped[str] = mapped_column(String, nullable=False)
    interval_sec: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items_found_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_empty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class FoundItem(Base):
    __tablename__ = "found_items"
    __table_args__ = (
        UniqueConstraint("vinted_item_id", "domain", name="uq_found_items_vinted_item_domain"),
        Index("ix_found_items_vinted_item_id", "vinted_item_id"),
        Index("ix_found_items_monitor_id", "monitor_id"),
        Index("ix_found_items_domain", "domain"),
        Index("ix_found_items_seller_id", "seller_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id"), nullable=False)
    vinted_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    domain: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    brand: Mapped[str] = mapped_column(String, nullable=False)
    size: Mapped[str] = mapped_column(String, nullable=False)
    condition: Mapped[str] = mapped_column(String, nullable=False)
    photo_url: Mapped[str] = mapped_column(String, nullable=False)
    item_url: Mapped[str] = mapped_column(String, nullable=False)
    seller_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ScraperSession(Base):
    __tablename__ = "scraper_sessions"
    __table_args__ = (
        Index("ix_scraper_sessions_domain", "domain"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String, nullable=False)
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    refresh_token: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    proxy_url: Mapped[str | None] = mapped_column(String, nullable=True)
    requests_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_requests: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    is_healthy: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HiddenSeller(Base):
    __tablename__ = "hidden_sellers"
    __table_args__ = (
        Index("ix_hidden_sellers_seller_id", "seller_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seller_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    hidden_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AppSettings(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)


class SeenItem(Base):
    __tablename__ = "seen_items"
    __table_args__ = (
        UniqueConstraint("vinted_item_id", "domain", name="uq_seen_items_vinted_item_domain"),
        Index("ix_seen_items_vinted_item_id", "vinted_item_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vinted_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    domain: Mapped[str] = mapped_column(String, nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
