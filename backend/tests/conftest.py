"""Test fixtures. Forces a SQLite backend BEFORE any app import so the engine,
settings, and the FOR-UPDATE capability flag are all computed for SQLite.
"""

from __future__ import annotations

import os

# Must be set before importing anything under app.* (settings are cached at import).
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_apollo.db")
os.environ.setdefault("VERIFY_RETELL_SIGNATURE", "false")
os.environ.setdefault("ENVIRONMENT", "dev")

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest_asyncio  # noqa: E402

from app.cache import cache  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Department, Doctor, Slot  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _fresh_schema():
    cache.invalidate()  # drop any cached departments/doctors from a prior test
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db():
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def seeded(db):
    """Two departments, two doctors, and a handful of future slots each."""
    ortho = Department(name="Orthopedics")
    derma = Department(name="Dermatology")
    db.add_all([ortho, derma])
    await db.flush()

    d1 = Doctor(name="Dr. Bone", department_id=ortho.id, experience=20)
    d2 = Doctor(name="Dr. Skin", department_id=derma.id, experience=10)
    db.add_all([d1, d2])
    await db.flush()

    base = datetime.now(tz=timezone.utc) + timedelta(days=1)
    base = base.replace(minute=0, second=0, microsecond=0)
    for doc in (d1, d2):
        for i in range(4):
            start = base + timedelta(minutes=15 * i)
            db.add(
                Slot(
                    doctor_id=doc.id,
                    start_time=start,
                    end_time=start + timedelta(minutes=15),
                    is_booked=False,
                )
            )
    await db.commit()
    return {"ortho": ortho, "derma": derma, "d1": d1, "d2": d2}
