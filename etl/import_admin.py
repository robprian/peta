#!/usr/bin/env python3
"""ETL batas wilayah BPS/Kemendagri -> geo.admin_regions (PostGIS).

Contoh:
  python etl/import_admin.py --data-dir data \
      --database-url postgresql://peta:peta_secret@localhost:5432/peta

Sumber data yang didukung (struktur repo ini):
  data/csv/62/{provinces,cities,subDistricts,villages}.csv
  data/geojson/62/**/<kode>.json

Desa/kelurahan pada dataset BPS ini tidak memiliki polygon. Script tetap
memasukkan atributnya; centroid dapat diisi dari:
  --village-centroids csv  (kolom: code,latitude,longitude)
  atau setelah import OSM: psql -f etl/link_osm_villages.sql
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import logging
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("etl.admin")

LEVEL_BY_LEN = {2: 1, 4: 2, 7: 3, 10: 4}
LEVEL_LABEL = {1: "provinsi", 2: "kab/kota", 3: "kecamatan", 4: "desa/kelurahan"}


@dataclass
class AdminRow:
    code: str
    level: int
    name: str
    parent_code: str | None
    province_code: str | None
    regency_code: str | None
    district_code: str | None
    postal_codes: list[str] = field(default_factory=list)
    lat: float | None = None
    lng: float | None = None
    geojson: dict[str, Any] | None = None
    source: str = "BPS"


def read_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def parse_postal(raw: str | None) -> list[str]:
    if not raw:
        return []
    values = {part.strip() for part in raw.split(",")}
    return sorted(v for v in values if len(v) == 5 and v.isdigit())


def parse_float(raw: str | None) -> float | None:
    try:
        value = (raw or "").strip()
        return float(value) if value else None
    except ValueError:
        return None


def build_rows(data_dir: str, province: str | None) -> list[AdminRow]:
    csv_dir = os.path.join(data_dir, "csv", "62")
    provinces = read_csv(os.path.join(csv_dir, "provinces.csv"))
    cities = read_csv(os.path.join(csv_dir, "cities.csv"))
    districts = read_csv(os.path.join(csv_dir, "subDistricts.csv"))
    villages = read_csv(os.path.join(csv_dir, "villages.csv"))

    def keep(code: str) -> bool:
        return province is None or code.startswith(province)

    rows: list[AdminRow] = []

    for r in provinces:
        code = r["Code"].strip()
        if not keep(code):
            continue
        rows.append(AdminRow(
            code=code, level=1, name=r["Name"].strip(), parent_code=None,
            province_code=code, regency_code=None, district_code=None,
            postal_codes=parse_postal(r.get("Postal")),
            lat=parse_float(r.get("Latitude")), lng=parse_float(r.get("Longitude")),
        ))

    city_by_code = {r["Code"].strip(): r for r in cities}
    for r in cities:
        code = r["Code"].strip()
        if not keep(code):
            continue
        parent = r["Parent"].strip()
        rows.append(AdminRow(
            code=code, level=2, name=r["Name"].strip(), parent_code=parent,
            province_code=parent, regency_code=code, district_code=None,
            postal_codes=parse_postal(r.get("Postal")),
            lat=parse_float(r.get("Latitude")), lng=parse_float(r.get("Longitude")),
        ))

    for r in districts:
        code = r["Code"].strip()
        if not keep(code):
            continue
        parent = r["Parent"].strip()
        city = city_by_code.get(parent)
        prov = city["Parent"].strip() if city else code[:2]
        rows.append(AdminRow(
            code=code, level=3, name=r["Name"].strip(), parent_code=parent,
            province_code=prov, regency_code=parent, district_code=code,
            postal_codes=parse_postal(r.get("Postal")),
            lat=parse_float(r.get("Latitude")), lng=parse_float(r.get("Longitude")),
        ))

    district_by_code = {r.code: r for r in rows if r.level == 3}

    for r in villages:
        code = r["Code"].strip()
        if not keep(code) or len(code) != 10:
            continue
        parent = r["Parent"].strip()
        district = district_by_code.get(parent)
        prov = district.province_code if district else code[:2]
        reg = district.regency_code if district else code[:4]
        rows.append(AdminRow(
            code=code, level=4, name=r["Name"].strip(), parent_code=parent,
            province_code=prov, regency_code=reg, district_code=parent,
            postal_codes=parse_postal(r.get("Postal")), source="BPS/Kemendagri",
        ))

    log.info("CSV: %s provinsi, %s kab/kota, %s kecamatan, %s desa",
             len(provinces), len(cities), len(districts), len(villages))
    return rows


def index_geojson(data_dir: str) -> dict[str, str]:
    """Peta kode -> path file GeoJSON (hanya level 1-3)."""
    pattern = os.path.join(data_dir, "geojson", "62", "**", "*.json")
    result: dict[str, str] = {}
    for path in glob.iglob(pattern, recursive=True):
        code = os.path.splitext(os.path.basename(path))[0]
        if len(code) in (2, 4, 7) and code.isdigit():
            result[code] = path
    log.info("GeoJSON: %s file batas wilayah ditemukan", len(result))
    return result


def load_geometry(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        features = data.get("features") or []
        if not features:
            return None
        return features[0].get("geometry")
    except (OSError, ValueError, KeyError):
        log.warning("Gagal membaca geometry %s", path, exc_info=True)
        return None


def load_village_centroids(path: str | None) -> dict[str, tuple[float, float]]:
    if not path:
        return {}
    result: dict[str, tuple[float, float]] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            lat, lng = parse_float(row.get("latitude")), parse_float(row.get("longitude"))
            code = (row.get("code") or "").strip()
            if code and lat is not None and lng is not None:
                result[code] = (lat, lng)
    log.info("Centroid desa dari CSV: %s", len(result))
    return result


def chunks(items: list[AdminRow], size: int) -> Iterable[list[AdminRow]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


INSERT_SQL = """
INSERT INTO geo.admin_regions AS a (
    code, kemendagri_code, level, name, parent_code,
    province_code, regency_code, district_code, postal_codes,
    geom, geom_simplified, centroid, bbox, area_km2, source, attrs
)
SELECT
    %(code)s::varchar, %(code)s::varchar, %(level)s::smallint, %(name)s::text,
    %(parent_code)s::varchar,
    %(province_code)s::varchar, %(regency_code)s::varchar, %(district_code)s::varchar,
    %(postal_codes)s::text[],
    g.geom,
    CASE WHEN g.geom IS NULL THEN NULL
         ELSE ST_SimplifyPreserveTopology(g.geom, 0.0005) END,
    COALESCE(
        CASE WHEN g.geom IS NULL THEN NULL ELSE ST_PointOnSurface(g.geom) END,
        CASE WHEN %(lat)s::double precision IS NULL THEN NULL
             ELSE ST_SetSRID(ST_MakePoint(
                 %(lng)s::double precision, %(lat)s::double precision), 4326) END
    ),
    CASE WHEN g.geom IS NULL THEN NULL ELSE ST_Envelope(g.geom) END,
    CASE WHEN g.geom IS NULL THEN NULL
         ELSE ST_Area(g.geom::geography) / 1000000.0 END,
    %(source)s::text,
    %(attrs)s::jsonb
FROM (
    SELECT CASE WHEN %(geojson)s::text IS NULL THEN NULL ELSE
        ST_Multi(ST_CollectionExtract(ST_MakeValid(
            ST_SetSRID(ST_GeomFromGeoJSON(%(geojson)s::text), 4326)
        ), 3))
    END AS geom
) g
ON CONFLICT (code) DO UPDATE SET
    kemendagri_code = EXCLUDED.kemendagri_code,
    level           = EXCLUDED.level,
    name            = EXCLUDED.name,
    parent_code     = EXCLUDED.parent_code,
    province_code   = EXCLUDED.province_code,
    regency_code    = EXCLUDED.regency_code,
    district_code   = EXCLUDED.district_code,
    postal_codes    = EXCLUDED.postal_codes,
    geom            = COALESCE(EXCLUDED.geom, a.geom),
    geom_simplified = COALESCE(EXCLUDED.geom_simplified, a.geom_simplified),
    centroid        = COALESCE(EXCLUDED.centroid, a.centroid),
    bbox            = COALESCE(EXCLUDED.bbox, a.bbox),
    area_km2        = COALESCE(EXCLUDED.area_km2, a.area_km2),
    source          = EXCLUDED.source,
    attrs           = a.attrs || EXCLUDED.attrs,
    updated_at      = now()
"""


def to_params(row: AdminRow) -> dict[str, Any]:
    return {
        "code": row.code,
        "level": row.level,
        "name": row.name,
        "parent_code": row.parent_code,
        "province_code": row.province_code,
        "regency_code": row.regency_code,
        "district_code": row.district_code,
        "postal_codes": row.postal_codes,
        "lat": row.lat,
        "lng": row.lng,
        "geojson": json.dumps(row.geojson, separators=(",", ":")) if row.geojson else None,
        "source": row.source,
        "attrs": Jsonb({
            "bps_level": row.level,
            "geometry_source": "BPS GeoJSON" if row.geojson else None,
        }),
    }


def import_rows(
    conn: psycopg.Connection,
    rows: list[AdminRow],
    paths: dict[str, str],
    *,
    batch_size: int = 50,
) -> int:
    total = 0
    skipped = 0
    ordered = sorted(rows, key=lambda r: (r.level, r.code))
    for batch in chunks(ordered, batch_size):
        params: list[dict[str, Any]] = []
        for row in batch:
            row.geojson = load_geometry(paths[row.code]) if row.code in paths else None
            params.append(to_params(row))
            row.geojson = None  # bebaskan memori

        try:
            with conn.cursor() as cur:
                cur.executemany(INSERT_SQL, params)
            conn.commit()
            total += len(params)
        except Exception:
            conn.rollback()
            log.warning("Batch gagal, fallback per baris", exc_info=True)
            for param in params:
                try:
                    with conn.cursor() as cur:
                        cur.execute(INSERT_SQL, param)
                    conn.commit()
                    total += 1
                except Exception:  # noqa: BLE001
                    conn.rollback()
                    # Baris tetap diimpor tanpa geometry agar atribut tidak hilang.
                    param["geojson"] = None
                    try:
                        with conn.cursor() as cur:
                            cur.execute(INSERT_SQL, param)
                        conn.commit()
                        total += 1
                        skipped += 1
                    except Exception:
                        conn.rollback()
                        log.exception("Gagal import %s", param.get("code"))

        level = batch[0].level
        log.info("  level %s (%s): %s baris", level, LEVEL_LABEL[level], total)

    if skipped:
        log.warning("%s baris diimpor tanpa geometry", skipped)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Import batas wilayah Indonesia ke PostGIS")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--province", help="Batasi ke prefix kode provinsi, mis. 32")
    parser.add_argument("--village-centroids", help="CSV code,latitude,longitude")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--skip-villages", action="store_true")
    parser.add_argument("--no-geometry", action="store_true")
    parser.add_argument("--truncate", action="store_true",
                        help="Kosongkan admin_regions sebelum import (HATI-HATI)")
    args = parser.parse_args()

    if not args.database_url:
        log.error("DATABASE_URL belum diset")
        return 2

    rows = build_rows(args.data_dir, args.province)
    if args.skip_villages:
        rows = [r for r in rows if r.level < 4]

    centroids = load_village_centroids(args.village_centroids)
    for row in rows:
        if row.level == 4 and row.code in centroids:
            row.lat, row.lng = centroids[row.code]

    paths = {} if args.no_geometry else index_geojson(args.data_dir)
    log.info("Akan mengimpor %s wilayah", len(rows))

    with psycopg.connect(args.database_url) as conn:
        if args.truncate:
            log.warning("TRUNCATE geo.admin_regions CASCADE")
            conn.execute("TRUNCATE geo.admin_regions CASCADE")
            conn.commit()

        run_id = conn.execute(
            "INSERT INTO geo.import_runs (dataset, source_file, status) "
            "VALUES ('admin_regions', %s, 'running') RETURNING id",
            (args.data_dir,),
        ).fetchone()[0]
        conn.commit()

        try:
            total = import_rows(conn, rows, paths, batch_size=args.batch_size)
            if not args.skip_villages:
                log.info("Membangun full_name hierarki ...")
                conn.execute("SELECT geo.refresh_region_full_names()")
                conn.commit()
            conn.execute("ANALYZE geo.admin_regions")
            conn.execute(
                "UPDATE geo.import_runs SET status='success', rows_loaded=%s, "
                "finished_at=now() WHERE id=%s",
                (total, run_id),
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
            log.exception("Import gagal")
            return 1

    log.info("Selesai: %s wilayah diimpor", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())


