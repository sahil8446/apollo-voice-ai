"""Domain errors + a global handler that returns LLM-friendly error bodies.

When a tool call fails, the voice agent reads the response back to the caller,
so error payloads carry a human-readable ``message`` the agent can speak —
never a raw stack trace or a bare 500.
"""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Base for expected, recoverable business errors.

    ``status_code`` shapes the HTTP response; ``message`` is safe to speak.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class SlotUnavailableError(DomainError):
    """Raised when the requested slot was taken between check and book.

    Carries ``alternatives`` so the agent can immediately offer other times
    instead of dead-ending the caller.
    """

    status_code = status.HTTP_409_CONFLICT
    code = "slot_unavailable"

    def __init__(self, message: str, alternatives: list | None = None) -> None:
        super().__init__(message)
        self.alternatives = alternatives or []


class ValidationError(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_error"


def register_exception_handlers(app) -> None:
    @app.exception_handler(DomainError)
    async def _domain_handler(_: Request, exc: DomainError) -> JSONResponse:
        body: dict = {"ok": False, "code": exc.code, "message": exc.message}
        if isinstance(exc, SlotUnavailableError):
            body["alternatives"] = exc.alternatives
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(Exception)
    async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        # Never leak internals to the agent; log the real cause elsewhere.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "ok": False,
                "code": "internal_error",
                "message": (
                    "Sorry, something went wrong on our end. "
                    "Could you try that again in a moment?"
                ),
            },
        )
