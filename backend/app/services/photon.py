"""Optional Photon (komoot) adapter for richer POI/address suggestions."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

# Photon mendukung bbox=minLon,minLat,maxLon,maxLat.
ID_BBOX = "94,-12,142,7"


async def photon_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.photon_url or limit <= 0:
        return []

    url = settings.photon_url.rstrip("/") + "/api"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(
                url,
                params={"q": query, "limit": limit, "lang": "id", "bbox": ID_BBOX},
                headers={"User-Agent": "peta-id/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        log.warning("Photon request failed", exc_info=True)
        return []

    results: list[dict[str, Any]] = []
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        name = props.get("name") or props.get("street") or props.get("city")
        if not name:
            continue
        parts = [
            props.get("street"), props.get("housenumber"),
            props.get("district"), props.get("city"),
            props.get("state"), props.get("postcode"),
        ]
        results.append(
            {
                "id": f"photon:{props.get('osm_type', '')}{props.get('osm_id', '')}",
                "kind": "place",
                "name": name,
                "label": ", ".join(str(p) for p in parts if p),
                "level": None,
                "lat": float(coords[1]),
                "lng": float(coords[0]),
                "bbox": _bbox(props.get("extent")),
                "postcode": props.get("postcode"),
                "category": props.get("osm_key"),
                "type": props.get("osm_value") or props.get("type"),
                "region": None,
                "score": 0.5,
                "geometry": None,
                "source": "photon",
            }
        )
    return results


def _bbox(extent: Any) -> list[float] | None:
    """Photon extent = [west, north, east, south] -> [w, s, e, n]."""
    if not extent or len(extent) != 4:
        return None
    try:
        west, north, east, south = (float(v) for v in extent)
    except (TypeError, ValueError):
        return None
    return [west, south, east, north]
