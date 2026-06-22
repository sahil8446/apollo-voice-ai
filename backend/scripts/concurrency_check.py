"""Concurrency proof: fire N simultaneous bookings at the SAME slot and assert
exactly one wins. Demonstrates the FOR UPDATE lock + partial unique index
prevent double-booking under real contention. Run against Postgres:

    DATABASE_URL=postgresql+asyncpg://... python -m scripts.concurrency_check
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.errors import SlotUnavailableError
from app.database import SessionLocal
from app.models import Slot
from app.services import booking_service


async def _attempt(slot_id: int, who: int) -> str:
    """Each task gets its OWN session — like separate web requests/processes."""
    async with SessionLocal() as db:
        try:
            await booking_service.book(
                db, patient_name=f"Caller {who}", patient_phone=f"90000000{who}",
                slot_id=slot_id,
            )
            return "won"
        except SlotUnavailableError:
            return "lost"


async def main() -> None:
    async with SessionLocal() as db:
        slot_id = (
            await db.execute(
                select(Slot.id).where(Slot.is_booked.is_(False)).order_by(Slot.id).limit(1)
            )
        ).scalar_one()

    n = 10
    results = await asyncio.gather(*[_attempt(slot_id, i) for i in range(n)])
    won = results.count("won")
    lost = results.count("lost")

    print(f"slot {slot_id}: {n} concurrent bookings -> won={won} lost={lost}")
    assert won == 1, f"EXPECTED exactly 1 winner, got {won} (DOUBLE-BOOKING!)"
    assert lost == n - 1
    print("PASS: no double-booking under concurrency.")


if __name__ == "__main__":
    asyncio.run(main())
