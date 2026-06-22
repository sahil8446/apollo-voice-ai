from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    department: str
    qualification: str | None = None
    designation: str | None = None
    experience: int | None = None


class FindDoctorResponse(BaseModel):
    """Returned to the agent after a doctor/department lookup. ``message`` is a
    ready-to-speak summary so the agent doesn't have to compose one."""

    ok: bool = True
    matched_department: str | None = None
    doctors: list[DoctorOut]
    message: str
