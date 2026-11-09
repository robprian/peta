#!/usr/bin/env python3
"""Import hasil `osmium export` (GeoJSON/GeoJSONSeq) ke tabel OSM PostGIS.

Pipeline (lihat etl/run_osm_import.sh):
  osmium tags-filter indonesia-latest.osm.pbf ... -o build/filtered.osm.pbf
  osmium export build/filtered.osm.pbf -f geojsonseq -o build/filtered.geojsonseq
  python etl/import_osm.py --input build/filtered.geojsonseq

Script ini sengaja tidak memakai osm2pgsql agar mudah dijalankan di mana saja;
untuk volume sangat besar, gunakan osm2pgsql flex (lihat docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger("etl.osm")

PLACE_RANK = {
    "city": 16, "town": 18, "village": 19, "hamlet": 20,
    "suburb": 21, "neighbourhood": 22, "quarter": 22,
    "locality": 25, "isolated_dwelling": 25,
}
PLACE_IMPORTANCE = {
    "city": 0.95, "town": 0.85, "village": 0.75, "hamlet": 0.6,
    "suburb": 0.7, "neighbourhood": 0.55, "quarter": 0.55,
    "locality": 0.5, "isolated_dwelling": 0.45,
}
CATEGORY_KEYS = (
    "place", "amenity", "shop", "tourism", "office",
    "healthcare", "leisure", "historic", "man_made",
)

PLACE_SQL = """
INSERT INTO geo.osm_places (
    osm_type, osm_id, name, display_name, category, type,
    lat, lon, geom,
    addr_housenumber, addr_street, addr_postcode, addr_village,
    addr_subdistrict, addr_city, addr_district, addr_state,
    tags, importance, rank_search
)
SELECT
    %(osm_type)s, %(osm_id)s, %(name)s, %(display_name)s, %(category)s, %(type)s,
    ST_Y(pt.geom), ST_X(pt.geom), pt.geom,
    %(addr_housenumber)s, %(addr_street)s, %(addr_postcode)s, %(addr_village)s,
    %(addr_subdistrict)s, %(addr_city)s, %(addr_district)s, %(addr_state)s,
    %(tags)s::jsonb, %(importance)s, %(rank_search)s
FROM (
    SELECT CASE
        WHEN GeometryType(g.geom) IN ('POLYGON', 'MULTIPOLYGON', 'LINESTRING', 'MULTILINESTRING')
            THEN ST_PointOnSurface(g.geom)
        ELSE g.geom
    END AS geom
    FROM (
        SELECT ST_SetSRID(ST_GeomFromGeoJSON(%(geojson)s), 4326) AS geom
    ) g
) pt
WHERE pt.geom IS NOT NULL
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
    tags = EXCLUDED.tags,
    importance = EXCLUDED.importance,
    rank_search = EXCLUDED.rank_search,
    updated_at = now()
"""

ROAD_SQL = """
INSERT INTO geo.osm_roads (osm_id, name, highway, ref, geom, tags)
SELECT
    %(osm_id)s, %(name)s, %(highway)s, %(ref)s,
    ST_LineMerge(ST_CollectionExtract(
        ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%(geojson)s), 4326)), 2
    )),
    %(tags)s::jsonb
WHERE GeometryType(ST_SetSRID(ST_GeomFromGeoJSON(%(geojson)s), 4326))
      IN ('LINESTRING', 'MULTILINESTRING')
ON CONFLICT (osm_id) DO UPDATE SET
    name = EXCLUDED.name,
    highway = EXCLUDED.highway,
    ref = EXCLUDED.ref,
    geom = EXCLUDED.geom,
    tags = EXCLUDED.tags
"""


def feature_id(props: dict[str, Any]) -> tuple[str, int] | None:
    raw_type = str(props.get("@type") or props.get("type") or "").lower()
    raw_id = props.get("@id") or props.get("id")
    if raw_id is None:
        return None

    text = str(raw_id)
    if "/" in text:                       # "node/123"
        prefix, text = text.split("/", 1)
        raw_type = raw_type or prefix
    elif text[:1] in ("n", "w", "r") and text[1:].isdigit():
        raw_type = raw_type or {"n": "node", "w": "way", "r": "relation"}[text[0]]
        text = text[1:]

    osm_type = {"node": "n", "way": "w", "relation": "r"}.get(raw_type)
    if osm_type is None:
        return None
    try:
        return osm_type, int(text)
    except ValueError:
        return None


def classify(props: dict[str, Any]) -> tuple[str | None, str | None]:
    for key in CATEGORY_KEYS:
        value = props.get(key)
        if value:
            return key, str(value)
    return None, None


def display_name(props: dict[str, Any]) -> str:
    street = props.get("addr:street")
    number = props.get("addr:housenumber")
    line1 = " ".join(v for v in (street, number) if v)
    parts = [
        line1,
        props.get("addr:village") or props.get("addr:hamlet"),
        props.get("addr:subdistrict"),
        props.get("addr:city") or props.get("addr:town"),
        props.get("addr:state"),
        props.get("addr:postcode"),
    ]
    name = props.get("name")
    return ", ".join(v for v in [name, *parts] if v)


def place_params(props: dict[str, Any], ident: tuple[str, int], geometry: dict[str, Any]) -> dict[str, Any] | None:
    category, type_ = classify(props)
    name = props.get("name")
    if not name and props.get("addr:housenumber") and props.get("addr:street"):
        name = f"{props['addr:street']} {props['addr:housenumber']}"
        category, type_ = "address", "address"
    if not name or not category:
        return None
    return {
        "osm_type": ident[0],
        "osm_id": ident[1],
        "name": name,
        "display_name": display_name(props),
        "category": category,
        "type": type_,
        "geojson": json.dumps(geometry, separators=(",", ":")),
        "addr_housenumber": props.get("addr:housenumber"),
        "addr_street": props.get("addr:street"),
        "addr_postcode": props.get("addr:postcode"),
        "addr_village": props.get("addr:village") or props.get("addr:hamlet"),
        "addr_subdistrict": props.get("addr:subdistrict"),
        "addr_city": props.get("addr:city") or props.get("addr:town"),
        "addr_district": props.get("addr:county"),
        "addr_state": props.get("addr:state"),
        "tags": Jsonb({k: v for k, v in props.items() if not k.startswith("@")}),
        "importance": PLACE_IMPORTANCE.get(type_, 0.3 if category != "address" else 0.2),
        "rank_search": PLACE_RANK.get(type_, 30),
    }


def road_params(props: dict[str, Any], ident: tuple[str, int], geometry: dict[str, Any]) -> dict[str, Any] | None:
    highway = props.get("highway")
    if not highway or ident[0] == "n":
        return None
    name = props.get("name") or props.get("ref")
    if not name:
        return None
    return {
        "osm_id": ident[1],
        "name": name,
        "highway": str(highway),
        "ref": props.get("ref"),
        "geojson": json.dumps(geometry, separators=(",", ":")),
        "tags": Jsonb({k: v for k, v in props.items() if not k.startswith("@")}),
    }


def iter_features(path: str, limit: int | None = None) -> Iterable[dict[str, Any]]:
    count = 0
    with open(path, encoding="utf-8") as fh:
        first = fh.read(1)
        fh.seek(0)
        if first == "[":
            raise SystemExit("Gunakan GeoJSONSeq (satu Feature per baris), bukan array JSON.")
        if first == "{":
            # Coba FeatureCollection utuh; hanya untuk file kecil.
            try:
                data = json.load(fh)
            except ValueError:
                fh.seek(0)
                data = None
            if isinstance(data, dict) and data.get("type") == "FeatureCollection":
                for feature in data.get("features", []):
                    yield feature
                    count += 1
                    if limit and count >= limit:
                        return
                return
            if isinstance(data, dict) and data.get("type") == "Feature":
                yield data
                return
            fh.seek(0)

        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                feature = json.loads(line)
            except ValueError:
                continue
            if feature.get("type") == "Feature":
                yield feature
                count += 1
                if limit and count >= limit:
                    return


def flush(conn: psycopg.Connection, sql: str, params: list[dict[str, Any]], label: str) -> int:
    if not params:
        return 0
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, params)
        conn.commit()
        return len(params)
    except Exception:
        conn.rollback()
        log.warning("%s: batch gagal, fallback per baris", label, exc_info=True)
        ok = 0
        for param in params:
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, param)
                conn.commit()
                ok += 1
            except Exception:
                conn.rollback()
                log.debug("%s: lewati satu fitur", label, exc_info=True)
        return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Import OSM GeoJSONSeq ke PostGIS")
    parser.add_argument("--input", required=True, help="File .geojsonseq hasil osmium export")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit", type=int, help="Batasi jumlah feature (untuk uji coba)")
    parser.add_argument("--skip-roads", action="store_true")
    parser.add_argument("--skip-places", action="store_true")
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.database_url:
        log.error("DATABASE_URL belum diset")
        return 2
    if not os.path.exists(args.input):
        log.error("File tidak ditemukan: %s", args.input)
        return 2

    places: dict[tuple[str, int], dict[str, Any]] = {}
    roads: dict[int, dict[str, Any]] = {}
    features = 0
    inserted_places = 0
    inserted_roads = 0

    with psycopg.connect(args.database_url) as conn:
        if args.truncate:
            log.warning("TRUNCATE osm_places, osm_roads")
            conn.execute("TRUNCATE geo.osm_places, geo.osm_roads RESTART IDENTITY")
            conn.commit()

        run_id = conn.execute(
            "INSERT INTO geo.import_runs (dataset, source_file, status) "
            "VALUES ('osm', %s, 'running') RETURNING id",
            (args.input,),
        ).fetchone()[0]
        conn.commit()

        try:
            for feature in iter_features(args.input, args.limit):
                features += 1
                props = feature.get("properties") or {}
                geometry = feature.get("geometry")
                if not geometry:
                    continue
                ident = feature_id(props)
                if ident is None:
                    continue

                if not args.skip_roads and props.get("highway"):
                    road = road_params(props, ident, geometry)
                    if road:
                        roads[road["osm_id"]] = road

                if not args.skip_places:
                    place = place_params(props, ident, geometry)
                    if place:
                        places[(place["osm_type"], place["osm_id"])] = place

                if len(places) >= args.batch_size:
                    inserted_places += flush(conn, PLACE_SQL, list(places.values()), "places")
                    places.clear()
                if len(roads) >= args.batch_size:
                    inserted_roads += flush(conn, ROAD_SQL, list(roads.values()), "roads")
                    roads.clear()

                if features % 100_000 == 0:
                    log.info("  %s feature, %s place, %s road", features, inserted_places, inserted_roads)

            inserted_places += flush(conn, PLACE_SQL, list(places.values()), "places")
            inserted_roads += flush(conn, ROAD_SQL, list(roads.values()), "roads")

            conn.execute("ANALYZE geo.osm_places")
            conn.execute("ANALYZE geo.osm_roads")
            conn.execute(
                "UPDATE geo.import_runs SET status='success', rows_loaded=%s, "
                "finished_at=now() WHERE id=%s",
                (inserted_places + inserted_roads, run_id),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            conn.execute(
                "UPDATE geo.import_runs SET status='failed', notes=%s, finished_at=now() "
                "WHERE id=%s",
                (str(exc)[:1000], run_id),
            )
            conn.commit()
            log.exception("Import OSM gagal")
            return 1

    log.info(
        "Selesai: %s feature -> %s place, %s road",
        features, inserted_places, inserted_roads,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())


