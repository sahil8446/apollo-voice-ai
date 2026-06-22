"""GET /doctors — backs the Retell ``find_doctor`` tool."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.doctor import FindDoctorResponse
from app.services import doctor_service

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get("", response_model=FindDoctorResponse)
async def list_doctors(
    department: str | None = Query(
        default=None,
        description="Department or lay term/symptom, e.g. 'Orthopedics' or 'bone'.",
    ),
    name: str | None = Query(default=None, description="Partial doctor name."),
    db: AsyncSession = Depends(get_db),
) -> FindDoctorResponse:
    matched_dept, doctors = await doctor_service.find_doctors(
        db, department=department, name=name
    )

    if department and not doctors:
        return FindDoctorResponse(
            matched_department=None,
            doctors=[],
            message=(
                f"I couldn't match '{department}' to one of our departments. "
                "Could you describe what the appointment is for?"
            ),
        )

    if not doctors:
        return FindDoctorResponse(
            doctors=[],
            message="I couldn't find a matching doctor. Could you tell me the "
            "specialty or the doctor's name?",
        )

    names = ", ".join(d.name for d in doctors[:4])
    dept_phrase = f" in {matched_dept}" if matched_dept else ""
    message = (
        f"We have {len(doctors)} doctor(s){dept_phrase}: {names}"
        + ("." if len(doctors) <= 4 else ", among others.")
    )
    return FindDoctorResponse(
        matched_department=matched_dept, doctors=doctors, message=message
    )
