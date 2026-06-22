"""Liveness and readiness probes.

``/health/live`` answers "is the process up". ``/health/ready`` additionally
checks the DB round-trips — that's the one a load balancer should gate traffic
on, so a pod with a dead DB connection is pulled out of rotation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/health/live")
async def live() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/health/ready")
async def ready(db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(text("SELECT 1"))
    return {"status": "ready", "version": __version__}
