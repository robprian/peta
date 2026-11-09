"""Reverse geocoding orchestration and optional Nominatim enrichment."""

from __future__ import annotations

from typing import Any

import httpx

from .. import cache
from ..config import get_settings
from ..db import fetch_one

INDONESIA_BBOX = (94.0, -12.0, 142.0, 7.0)


def in_indonesia(lat: float, lng: float) -> bool:
    west, south, east, north = INDONESIA_BBOX
    return west <= lng <= east and south <= lat <= north


async def reverse_geocode(
    lat: float, lng: float, *, use_cache: bool = True
) -> dict[str, Any]:
    settings = get_settings()
    key = cache.make_key("reverse", {"lat": round(lat, 5), "lng": round(lng, 5)})

    if use_cache:
        cached = await cache.get(key)
        if cached is not None:
            cached["cached"] = True
            return cached

    row = await fetch_one(
        "SELECT geo.reverse_geocode(%(lat)s::float8, %(lng)s::float8) AS result",
        {"lat": lat, "lng": lng},
    )
    result: dict[str, Any] = (row or {}).get("result") or {
        "found": False,
        "reason": "no_result",
        "location": {"lat": lat, "lng": lng},
    }
    result["location"] = {"lat": lat, "lng": lng}

    # Opsional: lengkapi jalan/alamat dari Nominatim bila tabel OSM kosong.
    if settings.nominatim_url and result.get("found"):
        enriched = await _nominatim_reverse(lat, lng)
        if enriched:
            _merge_nominatim(result, enriched)
    elif settings.nominatim_url and not result.get("found"):
        enriched = await _nominatim_reverse(lat, lng)
        if enriched:
            result = enriched

    if use_cache and result.get("found"):
        await cache.put(key, result)
    return result


async def _nominatim_reverse(lat: float, lng: float) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.nominatim_url:
        return None
    url = settings.nominatim_url.rstrip("/") + "/reverse"
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(
                url,
                params={
                    "format": "jsonv2",
                    "lat": lat,
                    "lon": lng,
                    "addressdetails": 1,
                    "zoom": 18,
                    "accept-language": "id",
                },
                headers={"User-Agent": "peta-id/1.0 (geocoder; contact@example.com)"},
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    addr = data.get("address") or {}
    if not addr:
        return None

    def ref(kind: str, name_key: str) -> dict[str, str] | None:
        name = addr.get(name_key)
        return {"code": data.get("osm_type", "") + ":" + str(data.get("osm_id", "")), "name": name} if name else None

    province = addr.get("state") or addr.get("region")
    regency = addr.get("city") or addr.get("county") or addr.get("town")
    district = addr.get("suburb") or addr.get("city_district") or addr.get("district")
    village = addr.get("village") or addr.get("hamlet") or addr.get("neighbourhood")

    return {
        "found": True,
        "location": {"lat": lat, "lng": lng},
        "region": {
            "province": ref("province", "state"),
            "regency": {"code": "nominatim", "name": regency} if regency else None,
            "district": {"code": "nominatim", "name": district} if district else None,
            "village": {"code": "nominatim", "name": village} if village else None,
        },
        "address": {
            "line1": data.get("display_name"),
            "street": addr.get("road"),
            "housenumber": addr.get("house_number"),
            "village": village,
            "district": district,
            "regency": regency,
            "province": province,
            "postcode": addr.get("postcode"),
            "formatted": data.get("display_name"),
            "label": data.get("display_name"),
        },
        "nearest": {"road": None, "place": None},
        "match": {
            "method": "nearest",
            "level": 0,
            "approximate": True,
            "distance_m": None,
            "confidence": 0.5,
        },
        "source": "nominatim",
    }


def _merge_nominatim(result: dict[str, Any], extra: dict[str, Any]) -> None:
    """Isi hanya bagian yang kosong; data PostGIS tetap prioritas."""
    address = result.setdefault("address", {})
    source_address = extra.get("address") or {}
    for key in ("street", "housenumber", "postcode", "line1"):
        if not address.get(key) and source_address.get(key):
            address[key] = source_address[key]
    if not address.get("formatted") and source_address.get("formatted"):
        address["formatted"] = source_address["formatted"]
    if not (result.get("nearest") or {}).get("road") and source_address.get("street"):
        result.setdefault("nearest", {})["road"] = {
            "name": source_address["street"],
            "ref": None,
            "highway": None,
            "distance_m": None,
        }
