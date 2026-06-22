"""Helpers that turn DB rows into spoken-friendly text for the voice agent."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings

settings = get_settings()
_CLINIC_TZ = ZoneInfo(settings.clinic_timezone)


def to_clinic_tz(dt: datetime) -> datetime:
    """Render a stored (UTC-aware or naive) timestamp in clinic local time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(_CLINIC_TZ)


def speak_slot(start: datetime) -> str:
    """e.g. 'Monday 23 Jun, 10:15 AM' — natural for TTS to read aloud."""
    local = to_clinic_tz(start)
    # %-I isn't portable to Windows; strip a leading zero manually.
    hour12 = local.strftime("%I").lstrip("0") or "12"
    return f"{local.strftime('%A %d %b')}, {hour12}:{local.strftime('%M %p')}"
