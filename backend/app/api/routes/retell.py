"""Retell adapter — the endpoints Retell actually calls.

Retell custom functions don't issue REST verbs; when the LLM invokes a tool,
Retell POSTs a JSON envelope ``{name, args, call}`` to the tool's URL and reads
the JSON response back to the caller. These endpoints speak that contract and
delegate to the same services as the REST API, so there's one source of truth
for business logic.

IMPORTANT for voice UX: every tool returns HTTP 200. Retell treats any non-2xx
as a "tool call failed", which derails the conversation — so domain problems
(slot taken, missing info, not found) come back as 200 with ``ok:false`` and a
speakable ``message`` (plus ``alternatives`` on conflicts). The strict
REST API keeps its 4xx/409 status codes for the eval harness and admin UI.

The caller's phone number arrives in ``call.from_number`` — per spec, that's
how we identify the caller for lookup/reschedule/cancel without asking.
"""

from __future__ import annotations

import functools
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, SlotUnavailableError
from app.core.security import verify_retell_signature
from app.database import get_db
from app.models.appointment import AppointmentType
from app.services import (
    availability_service,
    booking_service,
    doctor_service,
    notifications,
)

router = APIRouter(
    prefix="/retell",
    tags=["retell"],
    dependencies=[Depends(verify_retell_signature)],
)


def voice_safe(fn):
    """Convert any DomainError into a 200 response with a speakable message,
    so Retell never sees a tool failure for an expected business case."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except DomainError as exc:
            body: dict[str, Any] = {
                "ok": False,
                "code": exc.code,
                "message": exc.message,
            }
            if isinstance(exc, SlotUnavailableError):
                body["alternatives"] = exc.alternatives
            return body

    return wrapper


class RetellEnvelope(BaseModel):
    name: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    call: dict[str, Any] | None = None

    def caller_phone(self) -> str | None:
        if not self.call:
            return None
        return self.call.get("from_number") or self.call.get("from")

    def call_id(self) -> str | None:
        if not self.call:
            return None
        return self.call.get("call_id") or self.call.get("id")


@router.post("/find_doctor")
@voice_safe
async def find_doctor(env: RetellEnvelope, db: AsyncSession = Depends(get_db)) -> dict:
    matched, doctors = await doctor_service.find_doctors(
        db,
        department=env.args.get("department") or env.args.get("specialty"),
        name=env.args.get("name"),
    )
    if not doctors:
        return {
            "ok": False,
            "doctors": [],
            "message": "I couldn't find a matching doctor. Could you tell me the "
            "specialty, symptom, or the doctor's name?",
        }
    names = ", ".join(d.name for d in doctors[:4])
    return {
        "ok": True,
        "matched_department": matched,
        "doctors": [d.model_dump() for d in doctors],
        "message": f"I found {len(doctors)} doctor(s)"
        + (f" in {matched}" if matched else "")
        + f": {names}.",
    }


@router.post("/check_availability")
@voice_safe
async def check_availability(
    env: RetellEnvelope, db: AsyncSession = Depends(get_db)
) -> dict:
    doctor_id = env.args.get("doctor_id")
    if doctor_id is None:
        return {"ok": False, "message": "Which doctor would you like me to check?"}
    doctor, slots = await availability_service.open_slots(
        db, doctor_id=int(doctor_id), date=env.args.get("date")
    )
    if not slots:
        return {
            "ok": True,
            "slots": [],
            "message": f"{doctor.name} has no open slots then. "
            "Want to try another date or doctor?",
        }
    previews = "; ".join(s.label for s in slots[:3])
    return {
        "ok": True,
        "doctor_id": doctor.id,
        "doctor_name": doctor.name,
        "slots": [s.model_dump(mode="json") for s in slots],
        "message": f"{doctor.name} has {len(slots)} open slot(s). "
        f"Soonest: {previews}.",
    }


@router.post("/book_appointment")
@voice_safe
async def book_appointment(
    env: RetellEnvelope,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    a = env.args
    missing = [k for k in ("patient_name", "slot_id") if not a.get(k)]
    if missing:
        labels = {"patient_name": "the patient's name", "slot_id": "which time slot"}
        return {
            "ok": False,
            "message": f"I still need {', '.join(labels[k] for k in missing)}.",
        }

    phone = a.get("patient_phone") or env.caller_phone()
    if not phone:
        return {"ok": False, "message": "What phone number should I book this under?"}

    appt = await booking_service.book(
        db,
        patient_name=a["patient_name"],
        patient_phone=phone,
        slot_id=int(a["slot_id"]),
        appt_type=AppointmentType(a.get("type", "new")),
        # Default idempotency to the call id so a retried tool call is safe.
        idempotency_key=a.get("idempotency_key") or env.call_id(),
    )
    # Fire-and-forget confirmation email (no-op unless SMTP is configured).
    background_tasks.add_task(
        notifications.send_booking_confirmation, appt, a.get("patient_email")
    )
    return {
        "ok": True,
        "appointment": appt.model_dump(mode="json"),
        "message": f"All set — {appt.patient_name} with {appt.doctor_name} "
        f"on {appt.label}.",
    }


@router.post("/reschedule_appointment")
@voice_safe
async def reschedule_appointment(
    env: RetellEnvelope, db: AsyncSession = Depends(get_db)
) -> dict:
    a = env.args
    if not a.get("appointment_id") or not a.get("new_slot_id"):
        return {
            "ok": False,
            "message": "I need the appointment and the new time to reschedule.",
        }
    appt = await booking_service.reschedule(
        db,
        appointment_id=int(a["appointment_id"]),
        new_slot_id=int(a["new_slot_id"]),
    )
    return {
        "ok": True,
        "appointment": appt.model_dump(mode="json"),
        "message": f"Done — moved to {appt.label} with {appt.doctor_name}.",
    }


@router.post("/cancel_appointment")
@voice_safe
async def cancel_appointment(
    env: RetellEnvelope, db: AsyncSession = Depends(get_db)
) -> dict:
    appointment_id = env.args.get("appointment_id")
    if appointment_id is None:
        return {"ok": False, "message": "Which appointment should I cancel?"}
    appt = await booking_service.cancel(db, appointment_id=int(appointment_id))
    return {
        "ok": True,
        "appointment_id": appt.id,
        "message": "That's cancelled. Anything else I can help with?",
    }


@router.post("/lookup_appointments")
@voice_safe
async def lookup_appointments(
    env: RetellEnvelope, db: AsyncSession = Depends(get_db)
) -> dict:
    phone = env.args.get("phone") or env.caller_phone()
    if not phone:
        return {"ok": False, "message": "What phone number should I look under?"}
    appts = await booking_service.lookup_by_phone(db, phone=phone)
    if not appts:
        return {
            "ok": True,
            "appointments": [],
            "message": "I don't see any appointments under that number.",
        }
    previews = "; ".join(f"{x.doctor_name} on {x.label}" for x in appts[:3])
    return {
        "ok": True,
        "appointments": [x.model_dump(mode="json") for x in appts],
        "message": f"I found {len(appts)} appointment(s): {previews}.",
    }
