"""Application configuration — 12-factor, environment-driven.

Every tunable is read from the environment so the same image runs in dev,
staging, and prod with no code change. Defaults are dev-safe; production
values come from the platform (Railway/Render) env vars.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Apollo Voice AI"
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    # Comma-separated origins for the admin UI; "*" only in dev.
    cors_origins: str = "*"

    # --- Database ---
    # asyncpg driver. Railway/Render inject DATABASE_URL; we normalize it below.
    database_url: str = Field(
        default="postgresql+asyncpg://apollo:apollo@localhost:5432/apollo_voice",
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30  # seconds to wait for a connection before erroring
    db_echo: bool = False

    # --- Security ---
    # Shared secret Retell signs webhook payloads with (HMAC-SHA256).
    retell_api_key: str = ""
    # If false (dev only), webhook signature verification is skipped.
    verify_retell_signature: bool = False
    # API key the admin dashboard must present.
    admin_api_key: str = "dev-admin-key-change-me"

    # --- Domain ---
    clinic_name: str = "Apollo Spectra Hospitals, Pune"
    # Slot granularity used by the seed generator (minutes).
    slot_minutes: int = 15
    # How many days forward to generate bookable slots.
    slot_horizon_days: int = 21
    # IANA timezone the clinic operates in.
    clinic_timezone: str = "Asia/Kolkata"

    # --- Caching ---
    cache_ttl_seconds: int = 300  # doctors/departments change rarely

    # --- Email notifications (Gmail SMTP) ---
    # All optional; email sending is enabled only when user + password are set.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""          # your Gmail address
    smtp_password: str = ""      # a Gmail App Password (NOT your login password)
    smtp_from: str = ""          # defaults to smtp_user if blank
    # Optional fixed address that gets a copy of every booking (clinic front desk).
    clinic_notify_email: str = ""

    @field_validator("database_url")
    @classmethod
    def normalize_db_url(cls, v: str) -> str:
        """Platforms hand out `postgres://...`; SQLAlchemy + asyncpg needs
        `postgresql+asyncpg://...`. Normalize transparently so DATABASE_URL
        works as-is."""
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://") and "+asyncpg" not in v:
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

    @property
    def notifications_enabled(self) -> bool:
        return bool(self.smtp_user and self.smtp_password)

    @property
    def email_from(self) -> str:
        return self.smtp_from or self.smtp_user


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — settings are read once per process."""
    return Settings()
