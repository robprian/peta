#!/usr/bin/env python3
"""Seed a self-contained demo dataset for the API.

The fixtures in ``frontend/demo/demo-data.json`` are the single source of
truth for both the static GitHub Pages demo and this database seed:

* province / regency / district polygons: BPS (via data/geojson)
* village / kelurahan polygons: OpenStreetMap administrative boundaries
* places and roads: OSM/Nominatim examples

Usage:
    python3 etl/seed_demo.py \
        --database-url postgresql://peta:peta_secret@localhost:5432/peta --reset
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import psycopg

log = logging.getLogger("etl.demo")

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "frontend/demo/demo-data.json"


def load_fixture() -> dict[str, Any]:
    with FIXTURE.open() as fh:
        return json.load(fh)


def hierarchy_codes(code: str, level: int) -> dict[str, str | None]:
    return {
        "province": code[:2] if level >= 1 else None,
        "regency": code[:4] if level >= 2 else None,
        "district": code[:7] if level >= 3 else None,
    }


REGION_SQL = """
WITH src AS (
    SELECT ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%(geojson)s), 4326)) AS geom
)
INSERT INTO geo.admin_regions (
    code, kemendagri_code, level, name, parent_code,
    province_code, regency_code, district_code, postal_codes,
    geom, geom_simplified, centroid, bbox, area_km2, source, attrs
)
SELECT
    %(code)s, %(code)s, %(level)s, %(name)s, %(parent)s,
    %(province)s, %(regency)s, %(district)s, %(postal)s::text[],
    src.geom,
    ST_SimplifyPreserveTopology(src.geom, 0.0001),
    ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326),
    ST_Envelope(src.geom),
    ST_Area(src.geom::geography) / 1000000.0,
    'demo',
    %(attrs)s::jsonb
FROM src
ON CONFLICT (code) DO UPDATE SET
    level = EXCLUDED.level,
    name = EXCLUDED.name,
    parent_code = EXCLUDED.parent_code,
    province_code = EXCLUDED.province_code,
    regency_code = EXCLUDED.regency_code,
    district_code = EXCLUDED.district_code,
    postal_codes = EXCLUDED.postal_codes,
    geom = EXCLUDED.geom,
    geom_simplified = EXCLUDED.geom_simplified,
    centroid = EXCLUDED.centroid,
    bbox = EXCLUDED.bbox,
    area_km2 = EXCLUDED.area_km2,
    source = EXCLUDED.source,
    attrs = geo.admin_regions.attrs || EXCLUDED.attrs,
    updated_at = now()
"""

PLACE_SQL = """
INSERT INTO geo.osm_places (
    osm_type, osm_id, name, display_name, category, type,
    lat, lon, geom,
    addr_housenumber, addr_street, addr_postcode, addr_village,
    addr_subdistrict, addr_city, addr_district, addr_state,
    tags, importance, rank_search
) VALUES (
    'n', %(osm_id)s, %(name)s, %(display_name)s, %(category)s, %(type)s,
    %(lat)s, %(lon)s, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326),
    NULL, NULL, %(postcode)s, %(village)s,
    %(district)s, %(regency)s, %(province)s, %(province)s,
    %(tags)s::jsonb, %(importance)s, %(rank_search)s
)
ON CONFLICT (osm_type, osm_id) DO UPDATE SET
    name = EXCLUDED.name,
    display_name = EXCLUDED.display_name,
    category = EXCLUDED.category,
    type = EXCLUDED.type,
    lat = EXCLUDED.lat,
    lon = EXCLUDED.lon,
    geom = EXCLUDED.geom,
    addr_postcode = EXCLUDED.addr_postcode,
    addr_village = EXCLUDED.addr_village,
    addr_subdistrict = EXCLUDED.addr_subdistrict,
    addr_city = EXCLUDED.addr_city,
    addr_district = EXCLUDED.addr_district,
    addr_state = EXCLUDED.addr_state,
    importance = EXCLUDED.importance,
    rank_search = EXCLUDED.rank_search,
    updated_at = now()
"""

ROAD_SQL = """
INSERT INTO geo.osm_roads (osm_id, name, highway, ref, geom, tags)
VALUES (
    %(osm_id)s, %(name)s, %(highway)s, %(ref)s,
    ST_SetSRID(ST_GeomFromText(%(wkt)s), 4326),
    '{"demo": true}'::jsonb
)
ON CONFLICT (osm_id) DO UPDATE SET
    name = EXCLUDED.name,
    highway = EXCLUDED.highway,
    ref = EXCLUDED.ref,
    geom = EXCLUDED.geom
"""


def region_params(item: dict[str, Any]) -> dict[str, Any]:
    codes = hierarchy_codes(item["code"], int(item["level"]))
    lat, lng = item["centroid"]
    return {
        "code": item["code"],
        "level": item["level"],
        "name": item["name"],
        "parent": item["parent"],
        **codes,
        "postal": item.get("postal") or [],
        "geojson": json.dumps(item["geometry"], separators=(",", ":")),
        "lat": lat,
        "lng": lng,
        "attrs": json.dumps({"demo": True, "source": "peta-demo-fixture"}),
    }


def place_params(index: int, item: dict[str, Any]) -> dict[str, Any]:
    params = dict(item)
    params["osm_id"] = int(item.get("id") or 900000000 + index)
    params["tags"] = json.dumps({"demo": True, "name": item["name"]})
    params["importance"] = 0.5
    params["rank_search"] = 30
    params["village"] = None
    params["district"] = None
    params["regency"] = None
    params["province"] = None
    return params


def road_params(index: int, item: dict[str, Any]) -> dict[str, Any]:
    coords = ", ".join(f"{lng} {lat}" for lat, lng in item["pts"])
    return {
        "osm_id": 800000000 + index,
        "name": item["name"],
        "highway": item.get("highway"),
        "ref": item.get("ref"),
        "wkt": f"LINESTRING({coords})",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo wilayah + OSM untuk Peta API")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--reset", action="store_true",
                        help="TRUNCATE admin_regions/osm_places/osm_roads sebelum seed")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.database_url:
        log.error("DATABASE_URL belum diset")
        return 2

    data = load_fixture()
    regions = data["regions"]
    places = data.get("places") or []
    roads = data.get("roads") or []

    try:
        with psycopg.connect(args.database_url) as conn:
            if args.reset:
                log.warning("TRUNCATE geo.admin_regions, geo.osm_places, geo.osm_roads")
                conn.execute(
                    "TRUNCATE geo.admin_regions, geo.osm_places, geo.osm_roads "
                    "RESTART IDENTITY CASCADE"
                )

            with conn.cursor() as cur:
                cur.executemany(
                    REGION_SQL,
                    [region_params(item) for item in sorted(regions, key=lambda r: r["level"])],
                )
                cur.executemany(
                    PLACE_SQL,
                    [place_params(i, item) for i, item in enumerate(places, start=1)],
                )
                cur.executemany(
                    ROAD_SQL,
                    [road_params(i, item) for i, item in enumerate(roads, start=1)],
                )

            conn.execute("SELECT geo.refresh_region_full_names()")
            conn.execute("ANALYZE geo.admin_regions")
            conn.execute("ANALYZE geo.osm_places")
            conn.execute("ANALYZE geo.osm_roads")
    except psycopg.Error as exc:
        log.error("Seed gagal: %s", str(exc).splitlines()[0])
        log.error("Pastikan migrasi sudah dijalankan: make migrate")
        return 1

    log.info("Demo siap: %s wilayah, %s place, %s road", len(regions), len(places), len(roads))
    log.info("Coba Jakarta: curl 'http://localhost:8000/api/v1/geo/reverse"
             "?lat=-6.2508944&lng=106.8230222'")
    log.info("Coba Bandung: curl 'http://localhost:8000/api/v1/geo/reverse"
             "?lat=-6.953196&lng=107.594708'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
