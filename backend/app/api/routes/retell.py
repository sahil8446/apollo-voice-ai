"""Retell adapter — the endpoints Retell actually calls.

Retell custom functions don't issue REST verbs; when the LLM invokes a tool,
Retell POSTs a JSON envelope ``{name, args, call}`` to the tool's URL and reads
the JSON response back to the caller. These endpoints speak that contract and
delegate to the same services as the REST API, so there's one source of truth
for business logic.

The caller's phone number arrives in ``call.from_number`` — per spec, that's
how we identify the caller for lookup/reschedule/cancel without asking.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.security import verify_retell_signature
from app.database import get_db
from app.models.appointment import AppointmentType
from app.services import availability_service, booking_service, doctor_service

router = APIRouter(
    prefix="/retell",
    tags=["retell"],
    dependencies=[Depends(verify_retell_signature)],
)


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
async def check_availability(
    env: RetellEnvelope, db: AsyncSession = Depends(get_db)
) -> dict:
    doctor_id = env.args.get("doctor_id")
    if doctor_id is None:
        raise ValidationError("I need to know which doctor first.")
    doctor, slots = await availability_service.open_slots(
        db, doctor_id=int(doctor_id), date=env.args.get("date")
    )
    if not slots:
        return {
            "ok": True,
            "slots": [],
            "message": f"Dr. {doctor.name} has no open slots then. "
            "Want to try another date or doctor?",
        }
    previews = "; ".join(s.label for s in slots[:3])
    return {
        "ok": True,
        "doctor_id": doctor.id,
        "doctor_name": doctor.name,
        "slots": [s.model_dump(mode="json") for s in slots],
        "message": f"Dr. {doctor.name} has {len(slots)} open slot(s). "
        f"Soonest: {previews}.",
    }


@router.post("/book_appointment")
async def book_appointment(
    env: RetellEnvelope, db: AsyncSession = Depends(get_db)
) -> dict:
    a = env.args
    required = ("patient_name", "slot_id")
    missing = [k for k in required if not a.get(k)]
    if missing:
        raise ValidationError(f"I still need: {', '.join(missing)}.")

    phone = a.get("patient_phone") or env.caller_phone()
    if not phone:
        raise ValidationError("I need a phone number to book under.")

    appt = await booking_service.book(
        db,
        patient_name=a["patient_name"],
        patient_phone=phone,
        slot_id=int(a["slot_id"]),
        appt_type=AppointmentType(a.get("type", "new")),
        # Default idempotency to the call id so a retried tool call is safe.
        idempotency_key=a.get("idempotency_key") or env.call_id(),
    )
    return {
        "ok": True,
        "appointment": appt.model_dump(mode="json"),
        "message": f"All set — {appt.patient_name} with Dr. {appt.doctor_name} "
        f"on {appt.label}.",
    }


@router.post("/reschedule_appointment")
async def reschedule_appointment(
    env: RetellEnvelope, db: AsyncSession = Depends(get_db)
) -> dict:
    a = env.args
    if not a.get("appointment_id") or not a.get("new_slot_id"):
        raise ValidationError("I need the appointment and the new slot.")
    appt = await booking_service.reschedule(
        db,
        appointment_id=int(a["appointment_id"]),
        new_slot_id=int(a["new_slot_id"]),
    )
    return {
        "ok": True,
        "appointment": appt.model_dump(mode="json"),
        "message": f"Done — moved to {appt.label} with Dr. {appt.doctor_name}.",
    }


@router.post("/cancel_appointment")
async def cancel_appointment(
    env: RetellEnvelope, db: AsyncSession = Depends(get_db)
) -> dict:
    appointment_id = env.args.get("appointment_id")
    if appointment_id is None:
        raise ValidationError("Which appointment should I cancel?")
    appt = await booking_service.cancel(db, appointment_id=int(appointment_id))
    return {
        "ok": True,
        "appointment_id": appt.id,
        "message": "That's cancelled. Anything else I can help with?",
    }


@router.post("/lookup_appointments")
async def lookup_appointments(
    env: RetellEnvelope, db: AsyncSession = Depends(get_db)
) -> dict:
    phone = env.args.get("phone") or env.caller_phone()
    if not phone:
        raise ValidationError("What phone number should I look under?")
    appts = await booking_service.lookup_by_phone(db, phone=phone)
    if not appts:
        return {
            "ok": True,
            "appointments": [],
            "message": "I don't see any appointments under that number.",
        }
    previews = "; ".join(f"Dr. {x.doctor_name} on {x.label}" for x in appts[:3])
    return {
        "ok": True,
        "appointments": [x.model_dump(mode="json") for x in appts],
        "message": f"I found {len(appts)} appointment(s): {previews}.",
    }
