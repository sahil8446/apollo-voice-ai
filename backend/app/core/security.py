"""Authentication: Retell webhook signature verification + admin API key.

Retell signs each tool-call request body with HMAC-SHA256 using the shared
API key. We recompute the signature and compare in constant time so a leaked
endpoint URL can't be abused to mutate appointments. The admin dashboard uses
a separate static API key — different trust boundary, different credential.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, HTTPException, Request, status

from app.config import get_settings

settings = get_settings()


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


async def verify_retell_signature(request: Request) -> None:
    """FastAPI dependency guarding Retell-facing endpoints.

    Disabled in dev (``verify_retell_signature=false``) so local calls and the
    eval harness work without a real key.
    """
    if not settings.verify_retell_signature:
        return

    signature = request.headers.get("x-retell-signature", "")
    if not signature or not settings.retell_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Retell signature",
        )

    body = await request.body()
    expected = hmac.new(
        settings.retell_api_key.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not _constant_time_eq(signature, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Retell signature",
        )


async def verify_admin_key(x_api_key: str = Header(default="")) -> None:
    """FastAPI dependency guarding the admin dashboard endpoints."""
    if not _constant_time_eq(x_api_key, settings.admin_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin API key",
        )
