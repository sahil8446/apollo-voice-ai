"""Open-slot lookup for a doctor, optionally narrowed to a date."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import NotFoundError, ValidationError
from app.models import Doctor, Slot
from app.schemas.availability import SlotOut
from app.services.formatting import speak_slot

settings = get_settings()
_CLINIC_TZ = ZoneInfo(settings.clinic_timezone)


def _slot_out(slot: Slot) -> SlotOut:
    return SlotOut(
        slot_id=slot.id,
        start_time=slot.start_time,
        end_time=slot.end_time,
        label=speak_slot(slot.start_time),
    )


async def get_doctor(db: AsyncSession, doctor_id: int) -> Doctor:
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError(f"I couldn't find a doctor with id {doctor_id}.")
    return doctor


async def open_slots(
    db: AsyncSession,
    *,
    doctor_id: int,
    date: str | None = None,
    limit: int = 6,
) -> tuple[Doctor, list[SlotOut]]:
    """Return up to ``limit`` future open slots for a doctor.

    If ``date`` (YYYY-MM-DD, clinic-local) is given, restrict to that day;
    otherwise return the soonest upcoming openings.
    """
    doctor = await get_doctor(db, doctor_id)

    now_utc = datetime.now(tz=ZoneInfo("UTC"))
    stmt = (
        select(Slot)
        .where(Slot.doctor_id == doctor_id)
        .where(Slot.is_booked.is_(False))
        .where(Slot.start_time >= now_utc)
        .order_by(Slot.start_time)
    )

    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValidationError(
                "Please give the date as YYYY-MM-DD, e.g. 2026-06-23."
            ) from exc
        day_start = datetime.combine(
            day, datetime.min.time(), tzinfo=_CLINIC_TZ
        )
        day_end = day_start + timedelta(days=1)
        stmt = stmt.where(Slot.start_time >= day_start).where(
            Slot.start_time < day_end
        )

    rows = (await db.execute(stmt.limit(limit))).scalars().all()
    return doctor, [_slot_out(s) for s in rows]


async def alternatives_for_slot(
    db: AsyncSession, slot: Slot, *, limit: int = 4
) -> list[SlotOut]:
    """Soonest open slots for the same doctor — offered when a slot is taken."""
    now_utc = datetime.now(tz=ZoneInfo("UTC"))
    stmt = (
        select(Slot)
        .where(Slot.doctor_id == slot.doctor_id)
        .where(Slot.is_booked.is_(False))
        .where(Slot.start_time >= now_utc)
        .where(Slot.id != slot.id)
        .order_by(Slot.start_time)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_slot_out(s) for s in rows]
