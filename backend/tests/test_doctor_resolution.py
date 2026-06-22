"""Vague-request -> department mapping (the 'robustness' rubric item)."""

from __future__ import annotations

import pytest

from app.services import doctor_service
from app.services.doctor_service import resolve_department

KNOWN = ["Orthopedics", "Dermatology", "ENT", "Internal Medicine"]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("a bone doctor", "Orthopedics"),
        ("my knee hurts", "Orthopedics"),
        ("skin rash", "Dermatology"),
        ("ear nose throat", "ENT"),
        ("fever and diabetes", "Internal Medicine"),
        ("Orthopedics", "Orthopedics"),
        ("ortho", "Orthopedics"),
        ("something totally unrelated", None),
    ],
)
def test_resolve_department(query, expected):
    assert resolve_department(query, KNOWN) == expected


async def test_find_doctors_by_symptom(db, seeded):
    matched, doctors = await doctor_service.find_doctors(db, department="bone")
    assert matched == "Orthopedics"
    assert any(d.name == "Dr. Bone" for d in doctors)


async def test_find_doctors_unknown_department_returns_empty(db, seeded):
    matched, doctors = await doctor_service.find_doctors(db, department="zzz nonsense")
    assert matched is None
    assert doctors == []
