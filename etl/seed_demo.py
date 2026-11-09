#!/usr/bin/env python3
"""Seed a tiny, self-contained demo dataset around Cibaduyut, Bandung.

Unlike import_admin.py this script does not need the BPS files: it inserts a
province/regency/district/village chain with synthetic polygons plus a few OSM
places/roads so every API endpoint can be exercised immediately.

Usage:
    python3 etl/seed_demo.py \
        --database-url postgresql://peta:peta_secret@localhost:5432/peta

The polygons are small rectangles around real coordinates. They are demo
fixtures, not authoritative boundaries. Use import_admin.py for real
BPS/Kemendagri boundaries.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

import psycopg

log = logging.getLogger("etl.demo")

# box = (min_lon, min_lat, max_lon, max_lat), point = (lat, lon)
REGIONS: list[dict[str, Any]] = [
    {"code": "32", "level": 1, "name": "JAWA BARAT", "parent": None, "province": "32",
         "regency": None, "district": None, "postal": ["40100", "40200"],
         "box": (107.500, -7.000, 107.750, -6.850), "point": (-6.9033, 107.6426)},
    {"code": "3273", "level": 2, "name": "BANDUNG", "parent": "32", "province": "32",
         "regency": "3273", "district": None, "postal": ["40100", "40200"],
         "box": (107.550, -6.980, 107.720, -6.870), "point": (-6.9033, 107.6426)},
    {"code": "3273040", "level": 3, "name": "BOJONGLOA KIDUL", "parent": "3273",
         "province": "32", "regency": "3273", "district": "3273040",
         "postal": ["40234", "40235", "40236", "40237", "40238", "40239"],
         "box": (107.585, -6.955, 107.610, -6.940), "point": (-6.9470, 107.5988)},
    {"code": "3273080", "level": 3, "name": "BANDUNG KIDUL", "parent": "3273",
         "province": "32", "regency": "3273", "district": "3273080",
         "postal": ["40266", "40267", "40268", "40269"],
         "box": (107.615, -6.965, 107.645, -6.945), "point": (-6.9559, 107.6296)},
    {"code": "3273040004", "level": 4, "name": "CIBADUYUT", "parent": "3273040",
         "province": "32", "regency": "3273", "district": "3273040", "postal": ["40236"],
         "box": (107.595, -6.950, 107.602, -6.944), "point": (-6.946966, 107.598788)},
    {"code": "3273040001", "level": 4, "name": "CIBADUYUT KIDUL", "parent": "3273040",
         "province": "32", "regency": "3273", "district": "3273040", "postal": ["40239"],
         "box": None, "point": (-6.9475, 107.5965)},
    {"code": "3273040002", "level": 4, "name": "CIBADUYUT WETAN", "parent": "3273040",
         "province": "32", "regency": "3273", "district": "3273040", "postal": ["40238"],
         "box": None, "point": (-6.9460, 107.6010)},
    {"code": "3273080001", "level": 4, "name": "BATUNUNGGAL", "parent": "3273080",
         "province": "32", "regency": "3273", "district": "3273080", "postal": ["40266"],
         "box": None, "point": (-6.9559, 107.6296)},
]

PLACES: list[dict[str, Any]] = [
    {"osm_type": "n", "osm_id": 900000001, "name": "Pasar Cibaduyut",
         "display_name": "Pasar Cibaduyut, Bojongloa Kidul, Bandung",
         "category": "amenity", "type": "marketplace", "lat": -6.9470, "lon": 107.5980,
         "importance": 0.55, "rank_search": 30,
         "addr_street": "Jalan Cibaduyut", "addr_housenumber": "1",
         "addr_postcode": "40236", "addr_village": "CIBADUYUT",
         "addr_subdistrict": "BOJONGLOA KIDUL", "addr_city": "BANDUNG",
         "addr_district": "BANDUNG", "addr_state": "JAWA BARAT"},
    {"osm_type": "n", "osm_id": 900000002, "name": "Cibaduyut",
         "display_name": "Cibaduyut, Bojongloa Kidul, Bandung, Jawa Barat",
         "category": "place", "type": "village", "lat": -6.946966, "lon": 107.598788,
         "importance": 0.75, "rank_search": 19,
         "addr_street": None, "addr_housenumber": None,
         "addr_postcode": "40236", "addr_village": "CIBADUYUT",
         "addr_subdistrict": "BOJONGLOA KIDUL", "addr_city": "BANDUNG",
         "addr_district": "BANDUNG", "addr_state": "JAWA BARAT"},
    {"osm_type": "n", "osm_id": 900000003, "name": "Bandung",
         "display_name": "Bandung, Jawa Barat, Indonesia",
         "category": "place", "type": "city", "lat": -6.9033, "lon": 107.6426,
         "importance": 0.95, "rank_search": 16,
         "addr_street": None, "addr_housenumber": None, "addr_postcode": None,
         "addr_village": None, "addr_subdistrict": None, "addr_city": "BANDUNG",
         "addr_district": "BANDUNG", "addr_state": "JAWA BARAT"},
    {"osm_type": "n", "osm_id": 900000004, "name": "Toko Sepatu Cibaduyut",
         "display_name": "Toko Sepatu Cibaduyut, Jalan Cibaduyut, Bandung",
         "category": "shop", "type": "shoes", "lat": -6.9465, "lon": 107.5977,
         "importance": 0.35, "rank_search": 30,
         "addr_street": "Jalan Cibaduyut", "addr_housenumber": "88",
         "addr_postcode": "40236", "addr_village": "CIBADUYUT",
         "addr_subdistrict": "BOJONGLOA KIDUL", "addr_city": "BANDUNG",
         "addr_district": "BANDUNG", "addr_state": "JAWA BARAT"},
]

ROADS: list[dict[str, Any]] = [
    {"osm_id": 800000001, "name": "Jalan Cibaduyut", "highway": "residential", "ref": None,
         "wkt": "LINESTRING(107.5978 -6.9510, 107.5982 -6.9470, 107.5990 -6.9430)"},
    {"osm_id": 800000002, "name": "Jalan Soekarno-Hatta", "highway": "trunk", "ref": "AH2",
         "wkt": "LINESTRING(107.5800 -6.9400, 107.6000 -6.9420, 107.6200 -6.9440)"},
    {"osm_id": 800000003, "name": "Jalan Kopo", "highway": "primary", "ref": None,
         "wkt": "LINESTRING(107.5850 -6.9600, 107.5900 -6.9500, 107.5950 -6.9400)"},
]

REGION_SQL = """
WITH src AS (
    SELECT
        CASE WHEN %(min_lon)s::float8 IS NOT NULL THEN
            ST_Multi(ST_MakeEnvelope(
                %(min_lon)s::float8, %(min_lat)s::float8,
                %(max_lon)s::float8, %(max_lat)s::float8, 4326))
        END AS geom,
        CASE WHEN %(lat)s::float8 IS NOT NULL THEN
            ST_SetSRID(ST_MakePoint(%(lng)s::float8, %(lat)s::float8), 4326)
        END AS pt
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
    CASE WHEN src.geom IS NULL THEN NULL
         ELSE ST_SimplifyPreserveTopology(src.geom, 0.0005) END,
    COALESCE(src.pt, ST_PointOnSurface(src.geom)),
    CASE WHEN src.geom IS NULL THEN NULL ELSE ST_Envelope(src.geom) END,
    CASE WHEN src.geom IS NULL THEN NULL
         ELSE ST_Area(src.geom::geography) / 1000000.0 END,
    'demo',
    '{"demo": true}'::jsonb
FROM src
ON CONFLICT (code) DO UPDATE SET
    level = EXCLUDED.level,
    name = EXCLUDED.name,
    parent_code = EXCLUDED.parent_code,
    province_code = EXCLUDED.province_code,
    regency_code = EXCLUDED.regency_code,
    district_code = EXCLUDED.district_code,
    postal_codes = EXCLUDED.postal_codes,
    geom = COALESCE(EXCLUDED.geom, geo.admin_regions.geom),
    geom_simplified = COALESCE(EXCLUDED.geom_simplified, geo.admin_regions.geom_simplified),
    centroid = COALESCE(EXCLUDED.centroid, geo.admin_regions.centroid),
    bbox = COALESCE(EXCLUDED.bbox, geo.admin_regions.bbox),
    area_km2 = COALESCE(EXCLUDED.area_km2, geo.admin_regions.area_km2),
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
    %(osm_type)s, %(osm_id)s, %(name)s, %(display_name)s, %(category)s, %(type)s,
    %(lat)s, %(lon)s, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326),
    %(addr_housenumber)s, %(addr_street)s, %(addr_postcode)s, %(addr_village)s,
    %(addr_subdistrict)s, %(addr_city)s, %(addr_district)s, %(addr_state)s,
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
    addr_housenumber = EXCLUDED.addr_housenumber,
    addr_street = EXCLUDED.addr_street,
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
    min_lon, min_lat, max_lon, max_lat = item["box"] or (None, None, None, None)
    lat, lng = item["point"] or (None, None)
    return {
        "code": item["code"],
        "level": item["level"],
        "name": item["name"],
        "parent": item["parent"],
        "province": item["province"],
        "regency": item["regency"],
        "district": item["district"],
        "postal": item["postal"],
        "min_lon": min_lon,
        "min_lat": min_lat,
        "max_lon": max_lon,
        "max_lat": max_lat,
        "lat": lat,
        "lng": lng,
    }


def place_params(item: dict[str, Any]) -> dict[str, Any]:
    params = dict(item)
    params["tags"] = json.dumps({"demo": True, "name": item["name"]})
    return params


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
                    [region_params(item) for item in sorted(REGIONS, key=lambda r: r["level"])],
                )
                cur.executemany(PLACE_SQL, [place_params(item) for item in PLACES])
                cur.executemany(ROAD_SQL, ROADS)

            conn.execute("SELECT geo.refresh_region_full_names()")
            conn.execute("ANALYZE geo.admin_regions")
            conn.execute("ANALYZE geo.osm_places")
            conn.execute("ANALYZE geo.osm_roads")
    except psycopg.Error as exc:
        log.error("Seed gagal: %s", str(exc).splitlines()[0])
        log.error("Pastikan migrasi sudah dijalankan: make migrate")
        return 1

    log.info("Demo siap: %s wilayah, %s place, %s road", len(REGIONS), len(PLACES), len(ROADS))
    log.info("Coba: curl 'http://localhost:8000/api/v1/geo/reverse?lat=-6.946966&lng=107.598788'")
    log.info("Cari: curl 'http://localhost:8000/api/v1/geo/search?q=Cibaduyut'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
