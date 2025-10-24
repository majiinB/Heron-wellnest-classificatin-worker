# app/utils/db_utils.py
"""
Utility functions for performing direct SQL queries using SQLAlchemy.
"""

from typing import Optional, Dict, Any, List
from sqlalchemy import text
from sqlalchemy.engine import Result
from app.config.datasource_config import SessionLocal


def _is_write_query(query: str) -> bool:
    """Check if query is a write operation that needs a commit."""
    if not query:
        return False
    q = query.strip().split()[0].upper()
    return q in ("INSERT", "UPDATE", "DELETE") or "RETURNING" in query.upper()


async def fetch_one(query: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Execute a query and return a single row as a dict (or None).
    Commits for write queries (INSERT/UPDATE/DELETE or queries with RETURNING).
    """
    async with SessionLocal() as session:
        result: Result = await session.execute(text(query), params or {})
        row = result.mappings().first()
        if _is_write_query(query):
            await session.commit()
        return dict(row) if row is not None else None


async def fetch_all(query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Execute a query and return all rows as a list of dicts.
    Commits for write queries.
    """
    async with SessionLocal() as session:
        result: Result = await session.execute(text(query), params or {})
        rows = result.mappings().all()
        if _is_write_query(query):
            await session.commit()
        return [dict(r) for r in rows] if rows else []


async def execute_query(query: str, params: Optional[Dict[str, Any]] = None):
    async with SessionLocal() as session:
        await session.execute(text(query), params or {})
        await session.commit()


async def execute(query: str, params: Optional[Dict[str, Any]] = None) -> int:
    """
    Execute a write/update/delete statement, commit, and return affected row count.
    """
    async with SessionLocal() as session:
        result: Result = await session.execute(text(query), params or {})
        await session.commit()
        try:
            rc = result.rowcount
            return int(rc) if rc is not None else 0
        except Exception:
            return 0