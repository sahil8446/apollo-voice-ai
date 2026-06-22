"""FastAPI application factory.

Stateless by construction: no module-level mutable request state, so running N
copies behind a load balancer needs zero code change. The factory wires logging,
middleware, error handlers, the API router, and (optionally) the admin SPA.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.router import api_router
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import RequestContextMiddleware
from app.logging_config import configure_logging, get_logger

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level, json_format=settings.is_prod)
    logger = get_logger("apollo.app")
    logger.info(
        "startup",
        extra={"environment": settings.environment, "version": __version__},
    )
    yield
    logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Voice-agent backend for Apollo Spectra Hospitals, Pune.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)

    # Serve the read-only admin dashboard if it's bundled alongside the app.
    admin_dir = Path(__file__).resolve().parents[2] / "admin-ui"
    if admin_dir.is_dir():
        app.mount(
            "/admin-ui",
            StaticFiles(directory=str(admin_dir), html=True),
            name="admin-ui",
        )

        @app.get("/", include_in_schema=False)
        async def root() -> FileResponse:
            return FileResponse(str(admin_dir / "index.html"))

    return app


app = create_app()
