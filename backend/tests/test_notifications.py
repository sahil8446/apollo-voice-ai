"""Confirmation-email behaviour: disabled = no-op, enabled = sent off-thread,
and booking is scheduled to trigger it. Never sends a real email in tests."""

from __future__ import annotations

import app.services.notifications as notif
from app.schemas.appointment import AppointmentOut


def _fake_appt() -> AppointmentOut:
    from datetime import datetime, timezone

    now = datetime(2026, 6, 24, 5, 30, tzinfo=timezone.utc)
    return AppointmentOut(
        id=1,
        patient_name="Asha",
        patient_phone="7972540242",
        doctor_id=1,
        doctor_name="Dr. Anand Jadhav",
        department="Orthopedics",
        type="new",
        status="booked",
        start_time=now,
        end_time=now,
        label="Wednesday 24 Jun, 11:00 AM",
    )


async def test_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(notif.settings, "smtp_user", "")
    monkeypatch.setattr(notif.settings, "smtp_password", "")
    sent = []
    monkeypatch.setattr(notif, "_send_sync", lambda *a, **k: sent.append(a))
    await notif.send_booking_confirmation(_fake_appt(), "patient@example.com")
    assert sent == []  # nothing sent when SMTP isn't configured


async def test_enabled_sends_to_patient_and_clinic(monkeypatch):
    monkeypatch.setattr(notif.settings, "smtp_user", "clinic@gmail.com")
    monkeypatch.setattr(notif.settings, "smtp_password", "app-password")
    monkeypatch.setattr(notif.settings, "clinic_notify_email", "frontdesk@apollo.test")

    captured = {}

    def _capture(msg, to_addrs):
        captured["to"] = to_addrs
        captured["subject"] = msg["Subject"]

    monkeypatch.setattr(notif, "_send_sync", _capture)
    await notif.send_booking_confirmation(_fake_appt(), "patient@example.com")

    assert "patient@example.com" in captured["to"]
    assert "frontdesk@apollo.test" in captured["to"]
    assert "Dr. Anand Jadhav" in captured["subject"]


async def test_send_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(notif.settings, "smtp_user", "clinic@gmail.com")
    monkeypatch.setattr(notif.settings, "smtp_password", "app-password")

    def _boom(*a, **k):
        raise OSError("smtp down")

    monkeypatch.setattr(notif, "_send_sync", _boom)
    # Must not raise — email failures can never break a booking.
    await notif.send_booking_confirmation(_fake_appt(), "patient@example.com")
