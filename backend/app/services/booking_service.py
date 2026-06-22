"""Booking, rescheduling, cancellation, and lookup — the concurrency-safe core.

DOUBLE-BOOKING is the failure mode that actually matters for a clinic, so the
write path defends against it twice:

  1. Pessimistic lock: we ``SELECT ... FOR UPDATE`` the slot row, so two
     concurrent bookings on the same slot are serialized — the second waits for
     the first to commit and then sees ``is_booked=True``.
  2. DB invariant: a partial unique index allows at most one ``status='booked'``
     appointment per slot. Even if locking were bypassed (replicas, a future
     refactor), the database physically rejects the second insert. We translate
     that IntegrityError into a graceful "slot taken, here are alternatives".

Idempotency: a repeated ``idempotency_key`` (e.g. Retell's call_id on a retry)
returns the original appointment instead of creating a duplicate.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.errors import NotFoundError, SlotUnavailableError, ValidationError
from app.models import Appointment, AppointmentStatus, AppointmentType, Doctor, Slot
from app.schemas.appointment import AppointmentOut
from app.services.availability_service import alternatives_for_slot
from app.services.formatting import speak_slot

settings = get_settings()
# SQLite (tests) doesn't support SELECT ... FOR UPDATE; the partial unique
# index still guarantees correctness there.
_SUPPORTS_FOR_UPDATE = not settings.database_url.startswith("sqlite")


def _appointment_out(appt: Appointment) -> AppointmentOut:
    return AppointmentOut(
        id=appt.id,
        patient_name=appt.patient_name,
        patient_phone=appt.patient_phone,
        doctor_id=appt.doctor_id,
        doctor_name=appt.doctor.name,
        department=appt.doctor.department.name,
        type=appt.type,
        status=appt.status,
        start_time=appt.slot.start_time,
        end_time=appt.slot.end_time,
        label=speak_slot(appt.slot.start_time),
    )


async def _lock_slot(db: AsyncSession, slot_id: int) -> Slot:
    stmt = select(Slot).where(Slot.id == slot_id)
    if _SUPPORTS_FOR_UPDATE:
        stmt = stmt.with_for_update()
    slot = (await db.execute(stmt)).scalar_one_or_none()
    if slot is None:
        raise NotFoundError("That time slot doesn't exist anymore.")
    return slot


async def _hydrate(db: AsyncSession, appt_id: int) -> Appointment:
    """Reload an appointment with doctor+department+slot eagerly loaded."""
    stmt = (
        select(Appointment)
        .where(Appointment.id == appt_id)
        .options(
            selectinload(Appointment.doctor).selectinload(Doctor.department),
            selectinload(Appointment.slot),
        )
    )
    return (await db.execute(stmt)).scalar_one()


async def book(
    db: AsyncSession,
    *,
    patient_name: str,
    patient_phone: str,
    slot_id: int,
    appt_type: AppointmentType = AppointmentType.NEW,
    idempotency_key: str | None = None,
) -> AppointmentOut:
    # Idempotent replay.
    if idempotency_key:
        existing = (
            await db.execute(
                select(Appointment).where(
                    Appointment.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing:
            return _appointment_out(await _hydrate(db, existing.id))

    slot = await _lock_slot(db, slot_id)
    if slot.is_booked:
        alts = await alternatives_for_slot(db, slot)
        raise SlotUnavailableError(
            "That slot was just taken. Here are the next available times.",
            alternatives=[a.model_dump(mode="json") for a in alts],
        )

    appt = Appointment(
        patient_name=patient_name,
        patient_phone=patient_phone,
        doctor_id=slot.doctor_id,
        slot_id=slot.id,
        type=appt_type.value,
        status=AppointmentStatus.BOOKED.value,
        idempotency_key=idempotency_key,
    )
    slot.is_booked = True
    db.add(appt)

    try:
        await db.commit()
    except IntegrityError:
        # Lost the race (or replicas/locking bypassed) — DB rejected the dupe.
        await db.rollback()
        fresh = await _lock_slot(db, slot_id)
        alts = await alternatives_for_slot(db, fresh)
        raise SlotUnavailableError(
            "That slot was just taken. Here are the next available times.",
            alternatives=[a.model_dump(mode="json") for a in alts],
        ) from None

    return _appointment_out(await _hydrate(db, appt.id))


async def reschedule(
    db: AsyncSession,
    *,
    appointment_id: int,
    new_slot_id: int,
) -> AppointmentOut:
    appt = await db.get(Appointment, appointment_id)
    if appt is None or appt.status != AppointmentStatus.BOOKED.value:
        raise NotFoundError("I couldn't find an active appointment to reschedule.")

    if new_slot_id == appt.slot_id:
        raise ValidationError("That's the same slot you're already booked into.")

    new_slot = await _lock_slot(db, new_slot_id)
    if new_slot.doctor_id != appt.doctor_id:
        raise ValidationError(
            "The new slot is for a different doctor. Reschedules stay with the "
            "same doctor — please cancel and book a new appointment instead."
        )
    if new_slot.is_booked:
        alts = await alternatives_for_slot(db, new_slot)
        raise SlotUnavailableError(
            "That new slot is already taken. Here are other open times.",
            alternatives=[a.model_dump(mode="json") for a in alts],
        )

    old_slot = await _lock_slot(db, appt.slot_id)
    old_slot.is_booked = False
    new_slot.is_booked = True
    appt.slot_id = new_slot.id

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        fresh = await _lock_slot(db, new_slot_id)
        alts = await alternatives_for_slot(db, fresh)
        raise SlotUnavailableError(
            "That new slot was just taken. Here are other open times.",
            alternatives=[a.model_dump(mode="json") for a in alts],
        ) from None

    return _appointment_out(await _hydrate(db, appt.id))


async def cancel(db: AsyncSession, *, appointment_id: int) -> Appointment:
    appt = await db.get(Appointment, appointment_id)
    if appt is None or appt.status != AppointmentStatus.BOOKED.value:
        raise NotFoundError("I couldn't find an active appointment to cancel.")

    slot = await _lock_slot(db, appt.slot_id)
    slot.is_booked = False
    appt.status = AppointmentStatus.CANCELLED.value
    # Free the unique key so the (now-cancelled) row can't block a future rebook
    # of the same slot under the same idempotency key.
    appt.idempotency_key = None
    await db.commit()
    return appt


async def lookup_by_phone(
    db: AsyncSession, *, phone: str, include_cancelled: bool = False
) -> list[AppointmentOut]:
    stmt = (
        select(Appointment)
        .where(Appointment.patient_phone == phone.strip())
        .options(
            selectinload(Appointment.doctor).selectinload(Doctor.department),
            selectinload(Appointment.slot),
        )
        .join(Slot, Appointment.slot_id == Slot.id)
        .order_by(Slot.start_time)
    )
    if not include_cancelled:
        stmt = stmt.where(Appointment.status == AppointmentStatus.BOOKED.value)

    rows = (await db.execute(stmt)).scalars().all()
    return [_appointment_out(a) for a in rows]
