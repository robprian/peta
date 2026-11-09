#!/usr/bin/env python3
"""Generate the static GitHub Pages demo fixture.

Sources:
  * BPS/Kemendagri boundaries (province, city, district) from data/geojson.
  * OpenStreetMap kelurahan/desa boundaries cached in frontend/demo/sources/osm.
  * BPS names and postal codes from data/csv/62.

Run from the repo root after placing the BPS extract under data/:

    python3 scripts/build_demo_fixture.py

The output frontend/demo/demo-data.json is committed so the Pages build does
not need the multi-hundred-MB source data.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend/demo/demo-data.json"
BPS = ROOT / "data/geojson/62"
OSM = ROOT / "frontend/demo/sources/osm"

# code, level, parent, BPS geojson path (None for villages), OSM village file
REGIONS: list[tuple[str, int, str | None, str | None, str | None]] = [
    ("31", 1, None, "31/31.json", None),
    ("32", 1, None, "32/32.json", None),
    ("3171", 2, "31", "31/3171/3171.json", None),
    ("3273", 2, "32", "32/3273/3273.json", None),
    ("3171070", 3, "3171", "31/3171/3171070/3171070.json", None),
    ("3273040", 3, "3273", "32/3273/3273040/3273040.json", None),
    ("3273080", 3, "3273", "32/3273/3273080/3273080.json", None),
    ("3171070001", 4, "3171070", None, "3171070001.json"),
    ("3171070002", 4, "3171070", None, "3171070002.json"),
    ("3171070003", 4, "3171070", None, "3171070003.json"),
    ("3171070004", 4, "3171070", None, "3171070004.json"),
    ("3171070005", 4, "3171070", None, "3171070005.json"),
    ("3273040001", 4, "3273040", None, "3273040001.json"),
    ("3273040002", 4, "3273040", None, "3273040002.json"),
    ("3273040003", 4, "3273040", None, "3273040003.json"),
    ("3273040004", 4, "3273040", None, "3273040004.json"),
    ("3273040005", 4, "3273040", None, "3273040005.json"),
    ("3273040006", 4, "3273040", None, "3273040006.json"),
    ("3273080001", 4, "3273080", None, "3273080001.json"),
    ("3273080002", 4, "3273080", None, "3273080002.json"),
    ("3273080003", 4, "3273080", None, "3273080003.json"),
    ("3273080004", 4, "3273080", None, "3273080004.json"),
]

TOLERANCE = {1: 0.0015, 2: 0.0008, 3: 0.00025, 4: 0.00012}


def read_csv(name: str) -> list[dict[str, str]]:
    with (ROOT / "data/csv/62" / name).open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def postal(value: str | None) -> list[str]:
    return sorted({v.strip() for v in (value or "").split(",") if len(v.strip()) == 5})


def perpendicular(p: list[float], a: list[float], b: list[float]) -> float:
    if a == b:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def douglas_peucker(points: list[list[float]], tolerance: float) -> list[list[float]]:
    if len(points) < 3:
        return points
    stack = [(0, len(points) - 1)]
    keep = {0, len(points) - 1}
    while stack:
        start, end = stack.pop()
        best, index = 0.0, None
        for i in range(start + 1, end):
            dist = perpendicular(points[i], points[start], points[end])
            if dist > best:
                best, index = dist, i
        if index is not None and best > tolerance:
            keep.add(index)
            stack.append((start, index))
            stack.append((index, end))
    return [points[i] for i in sorted(keep)]


def ring_area(ring: list[list[float]]) -> float:
    total = 0.0
    for i in range(len(ring) - 1):
        total += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(total) / 2


def ring_centroid(ring: list[list[float]]) -> tuple[float, float]:
    area = total_x = total_y = 0.0
    for i in range(len(ring) - 1):
        cross = ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
        area += cross
        total_x += (ring[i][0] + ring[i + 1][0]) * cross
        total_y += (ring[i][1] + ring[i + 1][1]) * cross
    area *= 0.5
    if abs(area) < 1e-12:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    return total_x / (6 * area), total_y / (6 * area)


def simplify_ring(ring: list[list[float]], tolerance: float) -> list[list[float]]:
    if ring[0] != ring[-1]:
        ring = [*ring, ring[0]]
    simplified = douglas_peucker(ring, tolerance)
    simplified = [
        [round(p[0], 6), round(p[1], 6)] for p in simplified
    ]
    # Drop consecutive duplicates created by rounding.
    out: list[list[float]] = []
    for point in simplified:
        if not out or point != out[-1]:
            out.append(point)
    if out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else ring


def simplify_geometry(geometry: dict[str, Any], tolerance: float) -> dict[str, Any]:
    kind = geometry["type"]
    if kind == "Polygon":
        rings = [simplify_ring(r, tolerance) for r in geometry["coordinates"]]
        polygons = [rings]
    elif kind == "MultiPolygon":
        polygons = [
            [simplify_ring(r, tolerance) for r in polygon]
            for polygon in geometry["coordinates"]
        ]
    else:
        raise ValueError(f"unsupported geometry: {kind}")

    kept = []
    for polygon in polygons:
        if ring_area(polygon[0]) < 2e-8:
            continue
        kept.append(polygon)
    if not kept:
        raise ValueError("geometry collapsed during simplification")

    if len(kept) == 1:
        return {"type": "Polygon", "coordinates": kept[0]}
    return {"type": "MultiPolygon", "coordinates": kept}


def geometry_meta(geometry: dict[str, Any]) -> tuple[list[float], list[float], float]:
    polygons = (
        [geometry["coordinates"]]
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    xs = [p[0] for poly in polygons for p in poly[0]]
    ys = [p[1] for poly in polygons for p in poly[0]]
    largest = max(polygons, key=lambda poly: ring_area(poly[0]))
    cx, cy = ring_centroid(largest[0])
    area = sum(ring_area(poly[0]) for poly in polygons)
    return [min(xs), min(ys), max(xs), max(ys)], [round(cy, 6), round(cx, 6)], area


def build_regions() -> list[dict[str, Any]]:
    provinces = {r["Code"]: r for r in read_csv("provinces.csv")}
    cities = {r["Code"]: r for r in read_csv("cities.csv")}
    districts = {r["Code"]: r for r in read_csv("subDistricts.csv")}
    villages = {r["Code"]: r for r in read_csv("villages.csv")}
    meta = {**provinces, **cities, **districts, **villages}

    regions = []
    for code, level, parent, bps_path, osm_file in REGIONS:
        if bps_path:
            with (BPS / bps_path).open() as fh:
                raw = json.load(fh)["features"][0]["geometry"]
        else:
            with (OSM / osm_file).open() as fh:
                raw = json.load(fh)["geojson"]
        geometry = simplify_geometry(raw, TOLERANCE[level])
        bbox, centroid, area = geometry_meta(geometry)
        row = meta[code]
        regions.append({
            "code": code,
            "level": level,
            "name": row["Name"].strip().upper(),
            "parent": parent,
            "postal": postal(row.get("Postal")),
            "bbox": [round(v, 6) for v in bbox],
            "centroid": centroid,
            "area": area,
            "geometry": geometry,
        })
    return regions


def build_places() -> list[dict[str, Any]]:
    return [
        {"id": 900000001, "name": "Pasar Cibaduyut",
         "display_name": "Pasar Cibaduyut, Kebon Lega, Bojongloa Kidul, Bandung",
         "category": "amenity", "type": "marketplace", "lat": -6.947, "lon": 107.598,
         "postcode": "40235"},
        {"id": 900000002, "name": "Cibaduyut",
         "display_name": "Cibaduyut, Bojongloa Kidul, Bandung, Jawa Barat",
         "category": "place", "type": "village", "lat": -6.953196, "lon": 107.594708,
         "postcode": "40236"},
        {"id": 900000003, "name": "Bandung",
         "display_name": "Bandung, Jawa Barat, Indonesia",
         "category": "place", "type": "city", "lat": -6.90331, "lon": 107.642621,
         "postcode": None},
        {"id": 900000004, "name": "Toko Sepatu Cibaduyut",
         "display_name": "Toko Sepatu Cibaduyut, Jalan Cibaduyut, Bandung",
         "category": "shop", "type": "shoes", "lat": -6.9465, "lon": 107.5977,
         "postcode": "40235"},
        {"id": 900000005, "name": "Wisma Mulia 2",
         "display_name": ("Wisma Mulia 2, Jalan Jenderal Gatot Subroto, "
                          "Kuningan Barat, Mampang Prapatan, Jakarta Selatan"),
         "category": "building", "type": "office", "lat": -6.2342466, "lon": 106.8220762,
         "postcode": "12950"},
        {"id": 900000006, "name": "Wisma Mulia",
         "display_name": ("Wisma Mulia, Jalan Jenderal Gatot Subroto, "
                          "Kuningan Barat, Mampang Prapatan, Jakarta Selatan"),
         "category": "building", "type": "office", "lat": -6.2349892, "lon": 106.8234108,
         "postcode": "12710"},
        {"id": 900000007, "name": "Mampang Prapatan IV",
         "display_name": ("Jalan Mampang Prapatan IV, Pela Mampang, "
                          "Mampang Prapatan, Jakarta Selatan"),
         "category": "highway", "type": "residential", "lat": -6.2508944, "lon": 106.8230222,
         "postcode": "12720"},
    ]


def build_roads() -> list[dict[str, Any]]:
    with (ROOT / "frontend/demo/sources/osm/jalan-cibaduyut.json").open() as fh:
        raw = json.load(fh)
    cibaduyut = [[lat, lng] for lng, lat in raw["geojson"]["coordinates"]]
    return [
        {"name": "Jalan Cibaduyut", "ref": None, "highway": "tertiary", "pts": cibaduyut},
        {"name": "Jalan Soekarno-Hatta", "ref": "AH2", "highway": "trunk",
         "pts": [[-6.94, 107.58], [-6.942, 107.6], [-6.944, 107.62]]},
        {"name": "Jalan Kopo", "ref": None, "highway": "primary",
         "pts": [[-6.96, 107.585], [-6.95, 107.59], [-6.94, 107.595]]},
        {"name": "Jalan Jenderal Gatot Subroto", "ref": None, "highway": "trunk",
         "pts": [[-6.2395, 106.8105], [-6.2375, 106.8165], [-6.2355, 106.822],
                 [-6.2335, 106.827], [-6.2315, 106.833]]},
        {"name": "Jalan Mampang Prapatan Raya", "ref": None, "highway": "primary",
         "pts": [[-6.2455, 106.8245], [-6.247, 106.824], [-6.249, 106.8235],
                 [-6.251, 106.823], [-6.253, 106.8225]]},
        {"name": "Jalan Mampang Prapatan IV", "ref": None, "highway": "residential",
         "pts": [[-6.2508944, 106.8213], [-6.2508944, 106.8230222],
                 [-6.2508944, 106.8248]]},
    ]


def main() -> None:
    data = {
        "version": 1,
        "attribution": (
            "Batas provinsi/kota/kecamatan: BPS. "
            "Batas desa/kelurahan: OpenStreetMap contributors (ODbL)."
        ),
        "regions": build_regions(),
        "places": build_places(),
        "roads": build_roads(),
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    size = OUT.stat().st_size
    print(f"wrote {OUT} ({size / 1024:.1f} KiB, {len(data['regions'])} regions)")


if __name__ == "__main__":
    main()
