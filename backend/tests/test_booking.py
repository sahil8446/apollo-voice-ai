"""Core booking-logic tests: happy path, conflict + alternatives, reschedule,
cancel, idempotency, and the DB-level double-booking guarantee."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import NotFoundError, SlotUnavailableError
from app.models import Appointment, AppointmentStatus, Slot
from app.services import booking_service


async def _slot_ids(db, doctor_id):
    rows = await db.execute(
        select(Slot.id).where(Slot.doctor_id == doctor_id).order_by(Slot.start_time)
    )
    return [r[0] for r in rows.all()]


async def test_happy_path_booking(db, seeded):
    slots = await _slot_ids(db, seeded["d1"].id)
    appt = await booking_service.book(
        db, patient_name="Asha", patient_phone="911", slot_id=slots[0]
    )
    assert appt.status == "booked"
    assert appt.doctor_name == "Dr. Bone"

    slot = await db.get(Slot, slots[0])
    assert slot.is_booked is True


async def test_double_booking_returns_conflict_with_alternatives(db, seeded):
    slots = await _slot_ids(db, seeded["d1"].id)
    await booking_service.book(db, patient_name="A", patient_phone="1", slot_id=slots[0])

    with pytest.raises(SlotUnavailableError) as exc:
        await booking_service.book(
            db, patient_name="B", patient_phone="2", slot_id=slots[0]
        )
    assert exc.value.alternatives, "must offer alternatives on conflict"


async def test_partial_unique_index_blocks_duplicate_active_booking(db, seeded):
    """The DB itself must reject two active bookings for one slot."""
    slots = await _slot_ids(db, seeded["d1"].id)
    db.add(
        Appointment(
            patient_name="A",
            patient_phone="1",
            doctor_id=seeded["d1"].id,
            slot_id=slots[0],
            status=AppointmentStatus.BOOKED.value,
        )
    )
    db.add(
        Appointment(
            patient_name="B",
            patient_phone="2",
            doctor_id=seeded["d1"].id,
            slot_id=slots[0],
            status=AppointmentStatus.BOOKED.value,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_idempotent_rebook_returns_same_appointment(db, seeded):
    slots = await _slot_ids(db, seeded["d1"].id)
    a1 = await booking_service.book(
        db, patient_name="A", patient_phone="1", slot_id=slots[0], idempotency_key="k1"
    )
    a2 = await booking_service.book(
        db, patient_name="A", patient_phone="1", slot_id=slots[0], idempotency_key="k1"
    )
    assert a1.id == a2.id


async def test_reschedule_frees_old_slot(db, seeded):
    slots = await _slot_ids(db, seeded["d1"].id)
    appt = await booking_service.book(
        db, patient_name="A", patient_phone="1", slot_id=slots[0]
    )
    moved = await booking_service.reschedule(
        db, appointment_id=appt.id, new_slot_id=slots[1]
    )
    assert moved.id == appt.id

    old = await db.get(Slot, slots[0])
    new = await db.get(Slot, slots[1])
    assert old.is_booked is False
    assert new.is_booked is True


async def test_cancel_frees_slot_and_hides_from_lookup(db, seeded):
    slots = await _slot_ids(db, seeded["d1"].id)
    appt = await booking_service.book(
        db, patient_name="A", patient_phone="555", slot_id=slots[0]
    )
    await booking_service.cancel(db, appointment_id=appt.id)

    slot = await db.get(Slot, slots[0])
    assert slot.is_booked is False

    active = await booking_service.lookup_by_phone(db, phone="555")
    assert active == []


async def test_cancel_nonexistent_raises(db, seeded):
    with pytest.raises(NotFoundError):
        await booking_service.cancel(db, appointment_id=999999)
