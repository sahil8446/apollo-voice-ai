"""Aggregate router — single mount point for the FastAPI app."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    admin,
    appointments,
    availability,
    doctors,
    health,
    retell,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(doctors.router)
api_router.include_router(availability.router)
api_router.include_router(appointments.router)
api_router.include_router(retell.router)
api_router.include_router(admin.router)
