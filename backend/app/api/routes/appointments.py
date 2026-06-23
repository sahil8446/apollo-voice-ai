"""Appointment endpoints — back the book / reschedule / cancel / lookup tools.

Mutating routes require a valid Retell signature in prod (no-op in dev). A
slot conflict raises ``SlotUnavailableError``, which the global handler turns
into a 409 carrying ``alternatives`` — so the agent never dead-ends.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_retell_signature
from app.database import get_db
from app.schemas.appointment import (
    AppointmentListResponse,
    BookingResponse,
    BookRequest,
    CancelResponse,
    RescheduleRequest,
)
from app.services import booking_service, notifications

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_retell_signature)],
)
async def book_appointment(
    payload: BookRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> BookingResponse:
    appt = await booking_service.book(
        db,
        patient_name=payload.patient_name,
        patient_phone=payload.patient_phone,
        slot_id=payload.slot_id,
        appt_type=payload.type,
        idempotency_key=payload.idempotency_key,
    )
    # Fire-and-forget confirmation email (no-op unless SMTP is configured).
    background_tasks.add_task(
        notifications.send_booking_confirmation, appt, payload.patient_email
    )
    return BookingResponse(
        appointment=appt,
        message=(
            f"Booked. {appt.patient_name} with {appt.doctor_name} "
            f"({appt.department}) on {appt.label}."
        ),
    )


@router.put(
    "/{appointment_id}",
    response_model=BookingResponse,
    dependencies=[Depends(verify_retell_signature)],
)
async def reschedule_appointment(
    payload: RescheduleRequest,
    appointment_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> BookingResponse:
    appt = await booking_service.reschedule(
        db, appointment_id=appointment_id, new_slot_id=payload.new_slot_id
    )
    return BookingResponse(
        appointment=appt,
        message=(
            f"Rescheduled. {appt.patient_name} now sees {appt.doctor_name} "
            f"on {appt.label}."
        ),
    )


@router.delete(
    "/{appointment_id}",
    response_model=CancelResponse,
    dependencies=[Depends(verify_retell_signature)],
)
async def cancel_appointment(
    appointment_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> CancelResponse:
    appt = await booking_service.cancel(db, appointment_id=appointment_id)
    return CancelResponse(
        appointment_id=appt.id,
        message="Your appointment has been cancelled. Is there anything else?",
    )


@router.get("", response_model=AppointmentListResponse)
async def lookup_appointments(
    phone: str = Query(..., min_length=4, description="Caller phone number."),
    include_cancelled: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> AppointmentListResponse:
    appts = await booking_service.lookup_by_phone(
        db, phone=phone, include_cancelled=include_cancelled
    )
    if not appts:
        message = "I don't see any appointments under that number."
    else:
        previews = "; ".join(
            f"{a.doctor_name} on {a.label}" for a in appts[:3]
        )
        message = f"I found {len(appts)} appointment(s): {previews}."
    return AppointmentListResponse(appointments=appts, message=message)
