"""SQLAlchemy ORM models. Importing this package registers every table on
``Base.metadata`` so Alembic autogenerate and ``create_all`` see them all.
"""

from app.models.appointment import Appointment, AppointmentStatus, AppointmentType
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.schedule import DoctorSchedule
from app.models.slot import Slot

__all__ = [
    "Department",
    "Doctor",
    "DoctorSchedule",
    "Slot",
    "Appointment",
    "AppointmentStatus",
    "AppointmentType",
]
