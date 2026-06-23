from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.appointment import AppointmentType
from app.schemas.availability import SlotOut


class BookRequest(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=160)
    patient_phone: str = Field(..., min_length=4, max_length=32)
    slot_id: int
    type: AppointmentType = AppointmentType.NEW
    # Optional: if provided, a confirmation email is sent to the patient.
    patient_email: str | None = Field(default=None, max_length=254)
    # Optional idempotency key; Retell can pass the call_id so retries are safe.
    idempotency_key: str | None = Field(default=None, max_length=80)

    @field_validator("patient_phone")
    @classmethod
    def strip_phone(cls, v: str) -> str:
        return v.strip()


class RescheduleRequest(BaseModel):
    new_slot_id: int
    idempotency_key: str | None = Field(default=None, max_length=80)


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_name: str
    patient_phone: str
    doctor_id: int
    doctor_name: str
    department: str
    type: str
    status: str
    start_time: datetime
    end_time: datetime
    label: str


class BookingResponse(BaseModel):
    ok: bool = True
    appointment: AppointmentOut
    message: str


class ConflictResponse(BaseModel):
    """409 body when a slot was taken — carries alternatives so the agent can
    immediately offer other times instead of failing the call."""

    ok: bool = False
    code: str = "slot_unavailable"
    message: str
    alternatives: list[SlotOut]


class AppointmentListResponse(BaseModel):
    ok: bool = True
    appointments: list[AppointmentOut]
    message: str


class CancelResponse(BaseModel):
    ok: bool = True
    appointment_id: int
    message: str
