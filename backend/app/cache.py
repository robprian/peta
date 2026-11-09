"""Cache layer: PostGIS-backed JSON cache plus an in-process L1 cache."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from .config import get_settings
from .db import connection, fetch_one

# key -> (expires_monotonic, payload)
_L1: dict[str, tuple[float, dict[str, Any]]] = {}
_L1_MAX = 1024


def make_key(prefix: str, payload: dict[str, Any]) -> str:
    raw = prefix + ":" + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def l1_get(key: str) -> dict[str, Any] | None:
    hit = _L1.get(key)
    if not hit:
        return None
    expires, value = hit
    if expires < time.monotonic():
        _L1.pop(key, None)
        return None
    return value


def l1_set(key: str, value: dict[str, Any]) -> None:
    if len(_L1) >= _L1_MAX:
        _L1.pop(next(iter(_L1)))
    _L1[key] = (time.monotonic() + 300, value)


async def get(key: str) -> dict[str, Any] | None:
    cached = l1_get(key)
    if cached is not None:
        return cached
    row = await fetch_one(
        "SELECT payload FROM geo.geocode_cache "
        "WHERE cache_key = %(key)s AND expires_at > now()",
        {"key": key},
    )
    if row is None:
        return None
    l1_set(key, row["payload"])
    return row["payload"]


async def put(key: str, value: dict[str, Any], ttl: int | None = None) -> None:
    ttl = ttl or get_settings().cache_ttl_seconds
    if ttl <= 0:
        return
    l1_set(key, value)
    async with connection() as conn:
        await conn.execute(
            """
            INSERT INTO geo.geocode_cache (cache_key, payload, expires_at)
            VALUES (%(key)s, %(payload)s::jsonb, now() + make_interval(secs => %(ttl)s))
            ON CONFLICT (cache_key) DO UPDATE
               SET payload = EXCLUDED.payload,
                   expires_at = EXCLUDED.expires_at,
                   created_at = now()
            """,
            {"key": key, "payload": json.dumps(value), "ttl": ttl},
        )


async def clear_expired() -> int:
    async with connection() as conn:
        cur = await conn.execute("DELETE FROM geo.geocode_cache WHERE expires_at < now()")
        return cur.rowcount
