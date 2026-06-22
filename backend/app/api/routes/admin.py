"""Admin endpoints — power the read-only staff dashboard.

Separate trust boundary from the Retell API: guarded by a static admin API
key (``X-API-Key``), never by the Retell signature. Read-only by design — the
voice agent is the only writer in the MVP.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import verify_admin_key
from app.database import get_db
from app.models import Appointment, AppointmentStatus, Doctor
from app.schemas.appointment import AppointmentListResponse
from app.services.booking_service import _appointment_out  # noqa: PLC2701

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(verify_admin_key)]
)


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)) -> dict:
    total = await db.scalar(select(func.count()).select_from(Appointment))
    booked = await db.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(Appointment.status == AppointmentStatus.BOOKED.value)
    )
    cancelled = await db.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(Appointment.status == AppointmentStatus.CANCELLED.value)
    )
    return {
        "total": total or 0,
        "booked": booked or 0,
        "cancelled": cancelled or 0,
    }


@router.get("/appointments", response_model=AppointmentListResponse)
async def all_appointments(
    status_filter: str | None = Query(default=None, alias="status"),
    phone: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_db),
) -> AppointmentListResponse:
    stmt = (
        select(Appointment)
        .options(
            selectinload(Appointment.doctor).selectinload(Doctor.department),
            selectinload(Appointment.slot),
        )
        .order_by(Appointment.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(Appointment.status == status_filter)
    if phone:
        stmt = stmt.where(Appointment.patient_phone == phone.strip())

    rows = (await db.execute(stmt)).scalars().all()
    appts = [_appointment_out(a) for a in rows]
    return AppointmentListResponse(
        appointments=appts, message=f"{len(appts)} appointment(s)."
    )
