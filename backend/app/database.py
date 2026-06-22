"""Async database engine, session factory, and base model.

The engine uses a tuned asyncpg connection pool so a single process can serve
many concurrent voice turns without exhausting Postgres. The service tier is
stateless, so scaling out is just "run more processes" — each gets its own pool.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _make_engine() -> AsyncEngine:
    # SQLite (tests) doesn't accept pool sizing args; branch on dialect.
    if settings.database_url.startswith("sqlite"):
        return create_async_engine(settings.database_url, echo=settings.db_echo)
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,  # transparently recycle connections dropped by PG/PgBouncer
    )


engine: AsyncEngine = _make_engine()

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped session.

    The session is rolled back and closed automatically; routes/services
    own their own ``commit()`` so the transaction boundary is explicit.
    """
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
