"""GET /availability — backs the Retell ``check_availability`` tool."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.availability import AvailabilityResponse
from app.services import availability_service

router = APIRouter(prefix="/availability", tags=["availability"])


@router.get("", response_model=AvailabilityResponse)
async def check_availability(
    doctor_id: int = Query(..., description="Doctor id from find_doctor."),
    date: str | None = Query(
        default=None, description="Optional day filter, YYYY-MM-DD (clinic local)."
    ),
    db: AsyncSession = Depends(get_db),
) -> AvailabilityResponse:
    doctor, slots = await availability_service.open_slots(
        db, doctor_id=doctor_id, date=date
    )

    if not slots:
        when = f" on {date}" if date else " in the coming days"
        message = (
            f"Dr. {doctor.name} has no open slots{when}. "
            "Would you like to try another date or another doctor?"
        )
    else:
        previews = "; ".join(s.label for s in slots[:3])
        message = (
            f"Dr. {doctor.name} has {len(slots)} open slot(s). "
            f"Soonest: {previews}."
        )

    return AvailabilityResponse(
        doctor_id=doctor.id,
        doctor_name=doctor.name,
        date=date,
        slots=slots,
        message=message,
    )
