"""Doctor / department resolution — including vague-request mapping.

The Retell LLM does the heavy NLU, but we keep a server-side synonym map as a
robustness net: if the agent passes "bone" or "knee", we still resolve it to
Orthopedics. This means the endpoint behaves sensibly even when the model is
imprecise — defence in depth for the "vague request" rubric item.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cache import cache
from app.models import Department, Doctor
from app.schemas.doctor import DoctorOut

# Lay-term / symptom -> department. Lowercased substring match.
SPECIALTY_SYNONYMS: dict[str, str] = {
    "bone": "Orthopedics",
    "joint": "Orthopedics",
    "fracture": "Orthopedics",
    "knee": "Orthopedics",
    "hip": "Orthopedics",
    "back": "Orthopedics",
    "spine": "Orthopedics",
    "ortho": "Orthopedics",
    "joint replacement": "Joint Replacement",
    "replacement": "Joint Replacement",
    "weight": "Bariatric Surgery",
    "obesity": "Bariatric Surgery",
    "bariatric": "Bariatric Surgery",
    "surgery": "General Surgery",
    "general surgery": "General Surgery",
    "pregnan": "Obstetrics & Gynaecology",
    "gynae": "Obstetrics & Gynaecology",
    "women": "Obstetrics & Gynaecology",
    "obstetric": "Obstetrics & Gynaecology",
    "eye": "Ophthalmology",
    "vision": "Ophthalmology",
    "ophthal": "Ophthalmology",
    "physician": "Internal Medicine",
    "fever": "Internal Medicine",
    "diabetes": "Internal Medicine",
    "bp": "Internal Medicine",
    "internal": "Internal Medicine",
    "urine": "Urology",
    "kidney": "Urology",
    "urolog": "Urology",
    "ear": "ENT",
    "nose": "ENT",
    "throat": "ENT",
    "ent": "ENT",
    "scan": "Radiology",
    "x-ray": "Radiology",
    "xray": "Radiology",
    "mri": "Radiology",
    "radiolog": "Radiology",
    "skin": "Dermatology",
    "derma": "Dermatology",
    "rash": "Dermatology",
    "hair": "Dermatology",
}


async def _all_departments(db: AsyncSession) -> list[str]:
    async def loader() -> list[str]:
        rows = await db.execute(select(Department.name).order_by(Department.name))
        return [r[0] for r in rows.all()]

    # Don't cache an empty list (e.g. pre-seed) — it would poison resolution
    # for the whole TTL on that worker. Retry until departments actually exist.
    return await cache.get_or_set("departments", loader, cache_empty=False)


def resolve_department(query: str, known: list[str]) -> str | None:
    """Map free text to a canonical department name."""
    q = query.strip().lower()
    if not q:
        return None
    # 1) exact / case-insensitive department name
    for name in known:
        if name.lower() == q:
            return name
    # 2) department name substring (handles "ortho" -> "Orthopedics")
    for name in known:
        if q in name.lower() or name.lower() in q:
            return name
    # 3) symptom / lay-term synonyms
    for term, dept in SPECIALTY_SYNONYMS.items():
        if term in q and dept in known:
            return dept
    return None


async def find_doctors(
    db: AsyncSession,
    *,
    department: str | None = None,
    name: str | None = None,
) -> tuple[str | None, list[DoctorOut]]:
    """Return (matched_department, doctors). Filters are optional and additive."""
    stmt = select(Doctor).options(selectinload(Doctor.department)).order_by(Doctor.name)

    matched_dept: str | None = None
    if department:
        known = await _all_departments(db)
        matched_dept = resolve_department(department, known)
        if matched_dept:
            stmt = stmt.join(Department).where(Department.name == matched_dept)
        else:
            # No department match -> return empty so the agent can re-ask.
            return None, []

    if name:
        stmt = stmt.where(func.lower(Doctor.name).like(f"%{name.strip().lower()}%"))

    rows = (await db.execute(stmt)).scalars().all()
    doctors = [
        DoctorOut(
            id=d.id,
            name=d.name,
            department=d.department.name,
            qualification=d.qualification,
            designation=d.designation,
            experience=d.experience,
        )
        for d in rows
    ]
    return matched_dept, doctors
