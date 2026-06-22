from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.doctor import Doctor


class Slot(Base):
    """A concrete bookable time unit for a doctor.

    ``is_booked`` is a denormalized fast-path flag used for availability
    queries and as the row we lock (``FOR UPDATE``) during booking. The
    authoritative guarantee against double-booking lives on ``appointments``
    (partial unique index) — this flag is the optimization, not the contract.
    """

    __tablename__ = "slots"
    __table_args__ = (
        # No two slots can start at the same time for one doctor.
        UniqueConstraint("doctor_id", "start_time", name="uq_slot_doctor_start"),
        # Hot path: "open slots for doctor X on day Y" -> index-only scan.
        Index("ix_slots_doctor_open", "doctor_id", "is_booked", "start_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_booked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    doctor: Mapped["Doctor"] = relationship(back_populates="slots")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="slot")
