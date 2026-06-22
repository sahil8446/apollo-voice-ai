"""Seed the database with Apollo data and generate bookable slots.

Run:  python -m app.seed.seed [--reset]

``--reset`` drops and recreates all tables first (destructive; dev/demo only).
Without it, the script is a no-op if data already exists, so it's safe to run
on every deploy as an idempotent bootstrap.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.logging_config import configure_logging, get_logger
from app.models import Department, Doctor, DoctorSchedule, Slot
from app.seed.data import DEPARTMENTS, DOCTORS, OPD_WINDOWS

settings = get_settings()
logger = get_logger("apollo.seed")
_CLINIC_TZ = ZoneInfo(settings.clinic_timezone)


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _generate_slots_for_window(
    doctor_id: int,
    day_of_week: int,
    start: time,
    end: time,
    *,
    base_date,
    horizon_days: int,
    step_minutes: int,
) -> list[Slot]:
    slots: list[Slot] = []
    for offset in range(horizon_days):
        day = base_date + timedelta(days=offset)
        if day.weekday() != day_of_week:
            continue
        cursor = datetime.combine(day, start, tzinfo=_CLINIC_TZ)
        window_end = datetime.combine(day, end, tzinfo=_CLINIC_TZ)
        while cursor + timedelta(minutes=step_minutes) <= window_end:
            slot_end = cursor + timedelta(minutes=step_minutes)
            slots.append(
                Slot(
                    doctor_id=doctor_id,
                    start_time=cursor,
                    end_time=slot_end,
                    is_booked=False,
                )
            )
            cursor = slot_end
    return slots


async def seed(*, reset: bool = False) -> None:
    if reset:
        logger.info("dropping_all_tables")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        existing = await db.scalar(select(func.count()).select_from(Doctor))
        if existing and not reset:
            logger.info("already_seeded", extra={"doctors": existing})
            return

        # Departments
        dept_by_name: dict[str, Department] = {}
        for name in DEPARTMENTS:
            dept = Department(name=name)
            db.add(dept)
            dept_by_name[name] = dept
        await db.flush()

        # Doctors + schedules
        base_date = datetime.now(tz=_CLINIC_TZ).date()
        total_slots = 0
        for name, dept_name, qualification, experience in DOCTORS:
            doctor = Doctor(
                name=name,
                department_id=dept_by_name[dept_name].id,
                qualification=qualification,
                designation="Consultant",
                experience=experience,
            )
            db.add(doctor)
            await db.flush()

            for dow, start_s, end_s in OPD_WINDOWS.get(name, []):
                start_t, end_t = _parse_hhmm(start_s), _parse_hhmm(end_s)
                db.add(
                    DoctorSchedule(
                        doctor_id=doctor.id,
                        day_of_week=dow,
                        start_time=start_t,
                        end_time=end_t,
                    )
                )
                slots = _generate_slots_for_window(
                    doctor.id,
                    dow,
                    start_t,
                    end_t,
                    base_date=base_date,
                    horizon_days=settings.slot_horizon_days,
                    step_minutes=settings.slot_minutes,
                )
                db.add_all(slots)
                total_slots += len(slots)

        await db.commit()
        logger.info(
            "seed_complete",
            extra={
                "departments": len(DEPARTMENTS),
                "doctors": len(DOCTORS),
                "slots": total_slots,
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Apollo Voice AI database.")
    parser.add_argument(
        "--reset", action="store_true", help="Drop and recreate all tables first."
    )
    args = parser.parse_args()
    configure_logging(settings.log_level, json_format=False)
    asyncio.run(seed(reset=args.reset))


if __name__ == "__main__":
    main()
