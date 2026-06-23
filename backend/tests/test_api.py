"""End-to-end API tests through the ASGI app, including the conflict path and
the Retell envelope adapter."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.main import app


@pytest_asyncio.fixture
async def client(db):
    # Route the app's DB dependency to the test session.
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_find_doctor_by_symptom(client, seeded):
    r = await client.get("/doctors", params={"department": "knee"})
    assert r.status_code == 200
    body = r.json()
    assert body["matched_department"] == "Orthopedics"
    assert body["doctors"]


async def test_full_booking_then_conflict(client, seeded):
    av = await client.get("/availability", params={"doctor_id": seeded["d1"].id})
    assert av.status_code == 200
    slot_id = av.json()["slots"][0]["slot_id"]

    booked = await client.post(
        "/appointments",
        json={"patient_name": "Asha", "patient_phone": "9000", "slot_id": slot_id},
    )
    assert booked.status_code == 201

    # Same slot again -> 409 with alternatives the agent can offer.
    conflict = await client.post(
        "/appointments",
        json={"patient_name": "Ravi", "patient_phone": "9001", "slot_id": slot_id},
    )
    assert conflict.status_code == 409
    body = conflict.json()
    assert body["code"] == "slot_unavailable"
    assert body["alternatives"]


async def test_retell_envelope_find_doctor(client, seeded):
    r = await client.post(
        "/retell/find_doctor",
        json={"name": "find_doctor", "args": {"department": "skin"}, "call": {}},
    )
    assert r.status_code == 200
    assert r.json()["matched_department"] == "Dermatology"


async def test_retell_book_uses_caller_phone(client, seeded):
    av = await client.get("/availability", params={"doctor_id": seeded["d2"].id})
    slot_id = av.json()["slots"][0]["slot_id"]
    r = await client.post(
        "/retell/book_appointment",
        json={
            "name": "book_appointment",
            "args": {"patient_name": "Caller", "slot_id": slot_id},
            "call": {"from_number": "+919999", "call_id": "abc"},
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # The caller's number should now find the appointment.
    look = await client.get("/appointments", params={"phone": "+919999"})
    assert look.json()["appointments"]


async def test_retell_missing_phone_returns_200_not_error(client, seeded):
    """Missing info must be a clean 200 re-ask, not a 4xx 'tool call failed'."""
    r = await client.post(
        "/retell/lookup_appointments",
        json={"name": "lookup_appointments", "args": {}, "call": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "phone number" in body["message"].lower()


async def test_retell_conflict_returns_200_with_alternatives(client, seeded):
    """A taken slot comes back as 200 + alternatives so the agent never fails."""
    av = await client.get("/availability", params={"doctor_id": seeded["d1"].id})
    slot_id = av.json()["slots"][0]["slot_id"]
    env = {"name": "book_appointment", "call": {"from_number": "+918888"}}

    first = await client.post(
        "/retell/book_appointment",
        json={**env, "args": {"patient_name": "A", "slot_id": slot_id}},
    )
    assert first.status_code == 200 and first.json()["ok"] is True

    second = await client.post(
        "/retell/book_appointment",
        json={**env, "args": {"patient_name": "B", "slot_id": slot_id}},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["ok"] is False
    assert body["alternatives"]


async def test_no_double_doctor_title_in_messages(client, seeded):
    """Doctor names already contain 'Dr.'; messages must not double it."""
    r = await client.post(
        "/retell/check_availability",
        json={"name": "check_availability", "args": {"doctor_id": seeded["d1"].id}, "call": {}},
    )
    assert "Dr. Dr." not in r.json()["message"]
