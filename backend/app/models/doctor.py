from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.department import Department
    from app.models.schedule import DoctorSchedule
    from app.models.slot import Slot


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    qualification: Mapped[str | None] = mapped_column(String(255))
    designation: Mapped[str | None] = mapped_column(String(160))
    experience: Mapped[int | None] = mapped_column(Integer)

    department: Mapped["Department"] = relationship(back_populates="doctors")
    schedules: Mapped[list["DoctorSchedule"]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan"
    )
    slots: Mapped[list["Slot"]] = relationship(back_populates="doctor")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Doctor {self.name}>"
