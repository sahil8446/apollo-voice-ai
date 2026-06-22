"""Apollo Spectra Hospitals, Pune — seed data.

Source: hospital/department/doctor data per Credihealth. Exact public OPD times
aren't published, so each doctor is assigned a realistic recurring weekly OPD
window (day_of_week: 0=Mon .. 6=Sun). Bookable slots are generated from these
windows at seed time — nothing is hardcoded into the booking path.
"""

from __future__ import annotations

# (name, department, qualification, experience_years)
DOCTORS: list[tuple[str, str, str, int]] = [
    ("Dr. Anand Jadhav", "Orthopedics", "MBBS, Dip Ortho, MCh Ortho", 32),
    ("Dr. Anand Kavi", "Orthopedics", "MBBS, MS Ortho", 27),
    ("Dr. Yogesh Somvanshi", "Orthopedics", "MBBS, Dip Ortho", 14),
    ("Dr. Aashish Arbat", "Joint Replacement", "MBBS, MS Ortho, MCh Ortho", 21),
    ("Dr. Jayshree Todkar", "Bariatric Surgery", "MBBS, MS Gen Surgery, Fellowship", 31),
    ("Dr. Avinash Vagha", "General Surgery", "MBBS, MS Gen Surgery, DNB", 25),
    ("Dr. Kiran Jadhav", "Obstetrics & Gynaecology", "MBBS, MS OBGY, DGO", 24),
    ("Dr. Hemant Todkar", "Ophthalmology", "MBBS, MS Ophthal, PGDMLS", 21),
    ("Dr. Nilima Mane", "Internal Medicine", "MBBS, MD Internal Medicine", 18),
    ("Dr. Hrishikesh T Joshi", "Internal Medicine", "MBBS, MD, PG Diabetology", 18),
    ("Dr. Suraj Susheel Lunavat", "Urology", "MBBS, MS Gen Surgery, DNB Urology", 15),
    ("Dr. Alkesh Oswal", "ENT", "MBBS, MS ENT, DNB", 14),
    ("Dr. Kiran Naiknaware", "Radiology", "MBBS, MD Radiology, Fellowship", 14),
    ("Dr. Mukta Shriram Tulpule", "Dermatology", "MBBS, MD", 13),
]

DEPARTMENTS: list[str] = [
    "Orthopedics",
    "Joint Replacement",
    "Bariatric Surgery",
    "General Surgery",
    "Obstetrics & Gynaecology",
    "Ophthalmology",
    "Internal Medicine",
    "Urology",
    "ENT",
    "Radiology",
    "Dermatology",
]

# Recurring weekly OPD windows, assigned realistically per doctor.
# Keyed by doctor name -> list of (day_of_week, start "HH:MM", end "HH:MM").
# Three clinic days/week is typical for consultant OPDs at a 40-bed unit.
OPD_WINDOWS: dict[str, list[tuple[int, str, str]]] = {
    "Dr. Anand Jadhav": [(0, "10:00", "13:00"), (2, "10:00", "13:00"), (4, "10:00", "13:00")],
    "Dr. Anand Kavi": [(0, "16:00", "19:00"), (3, "16:00", "19:00")],
    "Dr. Yogesh Somvanshi": [(1, "11:00", "14:00"), (4, "11:00", "14:00")],
    "Dr. Aashish Arbat": [(1, "10:00", "13:00"), (3, "10:00", "13:00"), (5, "10:00", "12:00")],
    "Dr. Jayshree Todkar": [(0, "11:00", "13:00"), (2, "16:00", "18:00")],
    "Dr. Avinash Vagha": [(1, "09:30", "12:30"), (4, "17:00", "19:00")],
    "Dr. Kiran Jadhav": [(0, "10:00", "13:00"), (2, "10:00", "13:00"), (5, "10:00", "12:00")],
    "Dr. Hemant Todkar": [(1, "10:00", "13:00"), (3, "16:00", "19:00")],
    "Dr. Nilima Mane": [(0, "09:00", "12:00"), (1, "09:00", "12:00"), (3, "09:00", "12:00")],
    "Dr. Hrishikesh T Joshi": [(2, "17:00", "20:00"), (5, "10:00", "13:00")],
    "Dr. Suraj Susheel Lunavat": [(1, "16:00", "19:00"), (4, "16:00", "19:00")],
    "Dr. Alkesh Oswal": [(0, "11:00", "14:00"), (3, "11:00", "14:00")],
    "Dr. Kiran Naiknaware": [(0, "09:00", "13:00"), (1, "09:00", "13:00"), (2, "09:00", "13:00"), (3, "09:00", "13:00"), (4, "09:00", "13:00")],
    "Dr. Mukta Shriram Tulpule": [(2, "10:00", "13:00"), (5, "10:00", "13:00")],
}
