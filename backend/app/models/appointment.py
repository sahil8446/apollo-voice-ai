from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.doctor import Doctor
    from app.models.slot import Slot


class AppointmentStatus(str, enum.Enum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


class AppointmentType(str, enum.Enum):
    NEW = "new"
    FOLLOW_UP = "follow-up"
    PROCEDURE = "procedure"


# Partial unique index — the authoritative anti-double-booking guarantee.
# At most ONE row per slot may have status='booked'. Two concurrent bookings
# racing on the same slot: one commits, the other hits a unique violation and
# is converted into a "slot taken, here are alternatives" response. The DB,
# not application code, is the final arbiter — correct at any scale.
_BOOKED = f"status = '{AppointmentStatus.BOOKED.value}'"

_one_booking_per_slot = Index(
    "uq_appointment_active_slot",
    "slot_id",
    unique=True,
    postgresql_where=text(_BOOKED),
    sqlite_where=text(_BOOKED),
)


class Appointment(Base):
    """Source of truth for a booking. Slots are derived/denormalized; an
    appointment row with status='booked' is what actually reserves a time."""

    __tablename__ = "appointments"
    __table_args__ = (
        _one_booking_per_slot,
        Index("ix_appointments_phone", "patient_phone"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_name: Mapped[str] = mapped_column(String(160), nullable=False)
    patient_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    slot_id: Mapped[int] = mapped_column(
        ForeignKey("slots.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[str] = mapped_column(
        String(20), default=AppointmentType.NEW.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=AppointmentStatus.BOOKED.value, nullable=False, index=True
    )
    # Idempotency: Retell may retry a tool call on a network blip. A repeated
    # key returns the original appointment instead of creating a duplicate.
    idempotency_key: Mapped[str | None] = mapped_column(
        String(80), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    doctor: Mapped["Doctor"] = relationship()
    slot: Mapped["Slot"] = relationship(back_populates="appointments")
