"""Async PostgreSQL/PostGIS connection pool and small query helpers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import get_settings

log = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None


async def init_pool() -> None:
    global _pool
    settings = get_settings()
    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        open=False,
        kwargs={
            "row_factory": dict_row,
            "autocommit": True,
            "options": f"-c statement_timeout={settings.statement_timeout_ms}",
            "application_name": "peta-api",
        },
    )
    await _pool.open(wait=True, timeout=15)
    log.info("PostGIS pool ready (min=%s max=%s)", settings.db_pool_min, settings.db_pool_max)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("Database pool has not been initialised")
    return _pool


@asynccontextmanager
async def connection() -> AsyncIterator[Any]:
    async with pool().connection() as conn:
        yield conn


async def fetch_one(query: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    async with connection() as conn:
        cur = await conn.execute(query, params or {})
        return await cur.fetchone()


async def fetch_all(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    async with connection() as conn:
        cur = await conn.execute(query, params or {})
        return await cur.fetchall()


async def healthcheck() -> dict[str, Any]:
    row = await fetch_one(
        "SELECT postgis_version() AS postgis_version, now() AS db_time"
    )
    return row or {}
