# app/config/datasource_config.py
"""
Async database configuration using SQLAlchemy 2.0 for direct SQL access.

Simplified for worker/services that:
- Query from existing tables (no ORM models)
- Perform read/write operations using raw SQL

Usage:
    from app.config.datasource_config import get_session, execute_query
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from app.config.env_config import env


# --- Build database URL ---
def _build_db_url() -> str:
    return (
        f"postgresql+asyncpg://{env.DB_USER}:{env.DB_PASSWORD}"
        f"@{env.DB_HOST}:{env.DB_PORT}/{env.DB_NAME}"
    )


DATABASE_URL = _build_db_url()

# --- Create async engine and session factory ---
engine = create_async_engine(
    DATABASE_URL,
    echo=getattr(env, "DB_ECHO", False),
    pool_pre_ping=True,
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


# --- Helper to get a session (for use in workers or FastAPI deps) ---
async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session