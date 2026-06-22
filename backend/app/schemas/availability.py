from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slot_id: int
    start_time: datetime
    end_time: datetime
    # Spoken-friendly label, e.g. "Monday 23 Jun, 10:15 AM".
    label: str


class AvailabilityResponse(BaseModel):
    ok: bool = True
    doctor_id: int
    doctor_name: str
    date: str | None = None
    slots: list[SlotOut]
    message: str
