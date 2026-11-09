"""Forward geocoding / autocomplete across admin regions + OSM places."""

from __future__ import annotations

import time
from typing import Any

from ..db import fetch_all
from ..schemas import RegionChain, RegionRef
from .photon import photon_search

SEARCH_SQL = """
WITH q AS (
    SELECT %(q)s::text AS raw,
           lower(%(q)s::text) AS norm,
           plainto_tsquery('simple', %(q)s::text) AS tsq
),
admin AS (
    SELECT
        'region'::text                              AS kind,
        r.code                                      AS id,
        r.name                                      AS name,
        coalesce(r.full_name, r.name)               AS label,
        r.level                                     AS level,
        COALESCE(ST_Y(r.centroid), ST_Y(ST_PointOnSurface(r.geom))) AS lat,
        COALESCE(ST_X(r.centroid), ST_X(ST_PointOnSurface(r.geom))) AS lng,
        CASE WHEN r.bbox IS NULL THEN NULL ELSE ARRAY[
            ST_XMin(r.bbox), ST_YMin(r.bbox), ST_XMax(r.bbox), ST_YMax(r.bbox)
        ] END                                         AS bbox,
        CASE WHEN cardinality(r.postal_codes) > 0
             THEN r.postal_codes[1] END              AS postcode,
        NULL::text                                   AS category,
        NULL::text                                   AS type,
        COALESCE(r.province_code,
                 CASE WHEN r.level = 1 THEN r.code END) AS province_code,
        p.name                                       AS province_name,
        COALESCE(r.regency_code,
                 CASE WHEN r.level = 2 THEN r.code END) AS regency_code,
        reg.name                                     AS regency_name,
        COALESCE(r.district_code,
                 CASE WHEN r.level = 3 THEN r.code END) AS district_code,
        d.name                                       AS district_name,
        CASE WHEN r.level = 4 THEN r.code END        AS village_code,
        CASE WHEN r.level = 4 THEN r.name END        AS village_name,
        CASE
            WHEN lower(r.name) = q.norm THEN 0
            WHEN lower(r.name) LIKE q.norm || '%%' THEN 1
            WHEN lower(coalesce(r.full_name, '')) LIKE '%%' || q.norm || '%%' THEN 2
            WHEN r.search_vector @@ q.tsq THEN 3
            ELSE 4
        END                                          AS match_rank,
        GREATEST(
            similarity(lower(r.name), q.norm),
            similarity(lower(coalesce(r.full_name, '')), q.norm)
        )::float8                                 AS score,
        CASE WHEN %(include_geometry)s::boolean
             THEN ST_AsGeoJSON(r.geom_simplified, 6)::jsonb
             ELSE NULL END                        AS geometry
    FROM geo.admin_regions r
    CROSS JOIN q
    LEFT JOIN geo.admin_regions p   ON p.code = r.province_code
    LEFT JOIN geo.admin_regions reg ON reg.code = COALESCE(r.regency_code,
                                         CASE WHEN r.level = 2 THEN r.code END)
    LEFT JOIN geo.admin_regions d   ON d.code = COALESCE(r.district_code,
                                         CASE WHEN r.level = 3 THEN r.code END)
    WHERE (r.centroid IS NOT NULL OR r.geom IS NOT NULL)
      AND (
            r.search_vector @@ q.tsq
         OR lower(r.name) LIKE '%%' || q.norm || '%%'
         OR lower(coalesce(r.full_name, '')) LIKE '%%' || q.norm || '%%'
         OR lower(r.name) %% q.norm
         OR r.code LIKE q.norm || '%%'
      )
    ORDER BY match_rank, score DESC, r.level ASC
    LIMIT %(candidate_limit)s
),
places AS (
    SELECT
        'place'::text                               AS kind,
        'osm:' || p.osm_type || p.osm_id::text      AS id,
        p.name                                      AS name,
        COALESCE(NULLIF(p.display_name, ''), p.name) AS label,
        NULL::smallint                              AS level,
        p.lat::float8                               AS lat,
        p.lon::float8                               AS lng,
        NULL::float8[]                              AS bbox,
        p.addr_postcode                             AS postcode,
        p.category                                  AS category,
        p.type                                      AS type,
        NULL::text                                  AS province_code,
        p.addr_state                                AS province_name,
        NULL::text                                  AS regency_code,
        p.addr_city                                 AS regency_name,
        NULL::text                                  AS district_code,
        p.addr_subdistrict                          AS district_name,
        NULL::text                                  AS village_code,
        p.addr_village                              AS village_name,
        CASE
            WHEN lower(p.name) = q.norm THEN 0
            WHEN lower(p.name) LIKE q.norm || '%%' THEN 1
            WHEN lower(coalesce(p.display_name, '')) LIKE '%%' || q.norm || '%%' THEN 2
            WHEN p.search_vector @@ q.tsq THEN 3
            ELSE 4
        END                                          AS match_rank,
        GREATEST(
            similarity(lower(p.name), q.norm),
            similarity(lower(coalesce(p.display_name, '')), q.norm)
        )::float8                                  AS score,
        NULL::jsonb                                  AS geometry
    FROM geo.osm_places p
    CROSS JOIN q
    WHERE p.name IS NOT NULL
      AND (
            p.search_vector @@ q.tsq
         OR lower(p.name) LIKE '%%' || q.norm || '%%'
         OR lower(coalesce(p.display_name, '')) LIKE '%%' || q.norm || '%%'
         OR lower(p.name) %% q.norm
      )
    ORDER BY match_rank, score DESC, p.importance DESC
    LIMIT %(candidate_limit)s
),
combined AS (
    SELECT * FROM admin
    UNION ALL
    SELECT * FROM places
)
SELECT *
FROM combined
WHERE (%(kind)s::text = 'all' OR kind = %(kind)s::text)
ORDER BY match_rank, score DESC, CASE kind WHEN 'region' THEN 0 ELSE 1 END
LIMIT %(limit)s::int
"""


async def search_places(
    query: str,
    limit: int = 5,
    kind: str = "all",
    include_geometry: bool = False,
) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    q = " ".join(query.strip().split())
    rows = await fetch_all(
        SEARCH_SQL,
        {
            "q": q,
            "limit": limit,
            "candidate_limit": max(limit * 8, 40),
            "kind": kind,
            "include_geometry": include_geometry,
        },
    )
    results = [_to_item(row) for row in rows]

    # Opsional: gabungkan Photon bila hasil lokal masih sedikit.
    if len(results) < limit:
        photon = await photon_search(q, limit=limit - len(results))
        seen = {(item["name"].lower(), round(item["lat"], 4), round(item["lng"], 4)) for item in results}
        for item in photon:
            fingerprint = (item["name"].lower(), round(item["lat"], 4), round(item["lng"], 4))
            if fingerprint not in seen:
                results.append(item)
                seen.add(fingerprint)
            if len(results) >= limit:
                break

    return results[:limit], round((time.perf_counter() - started) * 1000, 2)


def _to_item(row: dict[str, Any]) -> dict[str, Any]:
    region = None
    if row.get("province_name") or row.get("regency_name") or row.get("district_name"):
        region = RegionChain(
            province=RegionRef(code=row["province_code"], name=row["province_name"])
            if row.get("province_code") and row.get("province_name") else None,
            regency=RegionRef(code=row["regency_code"], name=row["regency_name"])
            if row.get("regency_code") and row.get("regency_name") else None,
            district=RegionRef(code=row["district_code"], name=row["district_name"])
            if row.get("district_code") and row.get("district_name") else None,
            village=RegionRef(code=row["village_code"], name=row["village_name"])
            if row.get("village_code") and row.get("village_name") else None,
        ).model_dump()

    geometry = row.get("geometry")
    if isinstance(geometry, str):
        import json
        geometry = json.loads(geometry)

    return {
        "id": str(row["id"]),
        "kind": row["kind"],
        "name": row["name"],
        "label": row["label"],
        "level": row.get("level"),
        "lat": float(row["lat"]),
        "lng": float(row["lng"]),
        "bbox": [float(v) for v in row["bbox"]] if row.get("bbox") else None,
        "postcode": row.get("postcode"),
        "category": row.get("category"),
        "type": row.get("type"),
        "region": region,
        "score": round(float(row["score"] or 0), 4),
        "geometry": geometry,
    }
