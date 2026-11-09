"""Admin region lookup, hierarchy tree, and boundary payloads."""

from __future__ import annotations

from typing import Any

from ..db import fetch_all, fetch_one

REGION_FIELDS = """
    r.code, r.name, r.level, r.parent_code, r.full_name, r.postal_codes,
    COALESCE(ST_Y(r.centroid), ST_Y(ST_PointOnSurface(r.geom))) AS lat,
    COALESCE(ST_X(r.centroid), ST_X(ST_PointOnSurface(r.geom))) AS lng,
    CASE WHEN r.bbox IS NULL THEN NULL ELSE ARRAY[
        ST_XMin(r.bbox), ST_YMin(r.bbox), ST_XMax(r.bbox), ST_YMax(r.bbox)
    ] END AS bbox
"""


def _serialize(row: dict[str, Any], include_geometry: bool = False) -> dict[str, Any]:
    item = {
        "code": row["code"],
        "name": row["name"],
        "level": row["level"],
        "parent_code": row.get("parent_code"),
        "full_name": row.get("full_name"),
        "postal_codes": list(row.get("postal_codes") or []),
        "centroid": (
            {"lat": float(row["lat"]), "lng": float(row["lng"])}
            if row.get("lat") is not None and row.get("lng") is not None
            else None
        ),
        "bbox": [float(v) for v in row["bbox"]] if row.get("bbox") else None,
    }
    if include_geometry and row.get("geometry") is not None:
        item["geometry"] = row["geometry"]
    return item


async def get_region(code: str, include_geometry: bool = False) -> dict[str, Any] | None:
    row = await fetch_one(
        f"""
        SELECT {REGION_FIELDS},
               CASE WHEN %(geom)s::boolean
                    THEN ST_AsGeoJSON(r.geom_simplified, 6)::jsonb END AS geometry,
               (
                   WITH RECURSIVE up AS (
                       SELECT p.code, p.name, p.level, p.parent_code, p.full_name
                       FROM geo.admin_regions p
                       WHERE p.code = (SELECT parent_code FROM geo.admin_regions WHERE code = %(code)s::varchar)
                       UNION ALL
                       SELECT p.code, p.name, p.level, p.parent_code, p.full_name
                       FROM geo.admin_regions p JOIN up ON p.code = up.parent_code
                   )
                   SELECT jsonb_agg(jsonb_build_object(
                       'code', up.code, 'name', up.name, 'level', up.level
                   ) ORDER BY up.level)
                   FROM up
               ) AS ancestors
        FROM geo.admin_regions r
        WHERE r.code = %(code)s::varchar
        """,
        {"code": code, "geom": include_geometry},
    )
    if row is None:
        return None
    result = _serialize(row, include_geometry)
    result["ancestors"] = row.get("ancestors") or []
    return result


async def get_hierarchy(
    *,
    code: str | None = None,
    parent_code: str | None = None,
    level: int | None = None,
    depth: int = 1,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_geometry: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if code is None and parent_code is None and level is None:
        level = 1  # default: provinsi saja

    params = {
        "code": code,
        "parent_code": parent_code,
        "level": level,
        "depth": max(0, min(depth, 4)),
        "q": f"%{q.strip()}%" if q else None,
        "limit": limit,
        "offset": offset,
        "geom": include_geometry,
    }

    rows = await fetch_all(
        f"""
        WITH RECURSIVE roots AS (
            SELECT r.*
            FROM geo.admin_regions r
            WHERE (%(code)s::varchar IS NULL OR r.code = %(code)s::varchar)
              AND (%(parent_code)s::varchar IS NULL OR r.parent_code = %(parent_code)s::varchar)
              AND (%(level)s::smallint IS NULL OR r.level = %(level)s::smallint)
              AND (%(q)s::text IS NULL OR r.name ILIKE %(q)s::text OR r.full_name ILIKE %(q)s::text)
            ORDER BY r.level, r.name
            LIMIT %(limit)s::int OFFSET %(offset)s::int
        ),
        tree AS (
            SELECT r.*, 0 AS rel_depth, ARRAY[r.code]::varchar[] AS path
            FROM roots r
            UNION ALL
            SELECT c.*, t.rel_depth + 1, t.path || c.code
            FROM geo.admin_regions c
            JOIN tree t ON c.parent_code = t.code
            WHERE t.rel_depth < %(depth)s::int
        )
        SELECT {REGION_FIELDS},
               r.rel_depth, r.path,
               CASE WHEN %(geom)s::boolean
                    THEN ST_AsGeoJSON(r.geom_simplified, 6)::jsonb END AS geometry
        FROM tree r
        ORDER BY r.path
        """,
        params,
    )

    nodes: dict[str, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []
    for row in rows:
        node = _serialize(row, include_geometry)
        node["children"] = []
        nodes[row["code"]] = node

    for row in rows:
        node = nodes[row["code"]]
        parent = nodes.get(row.get("parent_code"))
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)

    meta = {
        "count": len(roots),
        "nodes": len(rows),
        "depth": params["depth"],
        "level": level,
        "parent_code": parent_code,
        "q": q,
        "limit": limit,
        "offset": offset,
    }
    return roots, meta


async def get_boundary(
    code: str, simplify: float = 0.0005
) -> dict[str, Any] | None:
    row = await fetch_one(
        """
        SELECT r.code, r.name, r.level, r.full_name, r.postal_codes,
               ST_AsGeoJSON(
                   CASE WHEN %(simplify)s::double precision > 0
                        THEN ST_SimplifyPreserveTopology(r.geom, %(simplify)s::double precision)
                        ELSE r.geom END, 6
               )::jsonb AS geometry
        FROM geo.admin_regions r
        WHERE r.code = %(code)s::varchar AND r.geom IS NOT NULL
        """,
        {"code": code, "simplify": simplify},
    )
    if row is None:
        return None
    return {
        "type": "Feature",
        "id": row["code"],
        "properties": {
            "code": row["code"],
            "name": row["name"],
            "level": row["level"],
            "full_name": row.get("full_name"),
            "postal_codes": list(row.get("postal_codes") or []),
        },
        "geometry": row["geometry"],
    }
