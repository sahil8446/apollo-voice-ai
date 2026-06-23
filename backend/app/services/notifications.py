"""Email confirmations via Gmail SMTP (stdlib only — no extra dependency).

Designed to be invisible when not configured and harmless when it fails:
- If SMTP credentials aren't set, ``send_booking_confirmation`` is a no-op.
- Sending runs off the event loop (``asyncio.to_thread``) and is meant to be
  scheduled as a FastAPI BackgroundTask, so it never adds latency to a voice
  turn and never fails a booking if Gmail is slow or down.

Gmail setup: enable 2-Step Verification, create an App Password
(https://myaccount.google.com/apppasswords), and set SMTP_USER + SMTP_PASSWORD.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app.config import get_settings
from app.logging_config import get_logger
from app.schemas.appointment import AppointmentOut

settings = get_settings()
logger = get_logger("apollo.notifications")


def _recipients(patient_email: str | None) -> list[str]:
    """Patient (if collected) plus the optional clinic front-desk address."""
    out: list[str] = []
    if patient_email:
        out.append(patient_email.strip())
    if settings.clinic_notify_email:
        out.append(settings.clinic_notify_email.strip())
    return out


def _build_message(appt: AppointmentOut, to_addrs: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Appointment confirmed — {appt.doctor_name}, {appt.label}"
    msg["From"] = settings.email_from
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(
        f"Hello {appt.patient_name},\n\n"
        f"Your appointment at {settings.clinic_name} is confirmed:\n\n"
        f"  Doctor:     {appt.doctor_name} ({appt.department})\n"
        f"  Date/time:  {appt.label}\n"
        f"  Type:       {appt.type}\n"
        f"  Reference:  #{appt.id}\n\n"
        f"Please arrive 10 minutes early. To reschedule or cancel, just call us "
        f"back.\n\n— {settings.clinic_name}\n"
    )
    return msg


def _send_sync(msg: EmailMessage, to_addrs: list[str]) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg, to_addrs=to_addrs)


async def send_booking_confirmation(
    appt: AppointmentOut, patient_email: str | None = None
) -> None:
    if not settings.notifications_enabled:
        logger.debug("email_disabled", extra={"appointment_id": appt.id})
        return

    to_addrs = _recipients(patient_email)
    if not to_addrs:
        return  # nobody to notify

    msg = _build_message(appt, to_addrs)
    try:
        # smtplib is blocking; keep it off the event loop.
        await asyncio.to_thread(_send_sync, msg, to_addrs)
        logger.info(
            "email_sent",
            extra={"appointment_id": appt.id, "recipients": len(to_addrs)},
        )
    except Exception as exc:  # never let email failure surface to the caller
        logger.warning(
            "email_failed",
            extra={"appointment_id": appt.id, "error": str(exc)},
        )
