"""End-to-end tests against a migrated PostGIS database with demo data.

Run with::

    PETA_TEST_DATABASE_URL=postgresql://peta:peta_secret@127.0.0.1:55432/peta \
        pytest -m integration

The database must already contain the demo fixtures from
``python etl/seed_demo.py`` (the same BPS/OSM boundaries used by the static
GitHub Pages demo).
"""

from __future__ import annotations

import psycopg
import pytest

pytestmark = pytest.mark.integration

VILLAGE_CODE = "3273040004"
DISTRICT_CODE = "3273040"
# True Cibaduyut centroid from the BPS/OSM fixture (not the Bojongloa Kidul
# centroid, which falls inside Kebon Lega).
CENTER = {"lat": -6.953196, "lng": 107.594708}
# Requested Jakarta checks.
MAMPANG_IV = {"lat": -6.2508944, "lng": 106.8230222}
WISMA_MULIA_2 = {"lat": -6.2342466, "lng": 106.8220762}


def test_health_reports_postgis(live_client):
    response = live_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["postgis"]


def test_locate_admin_sql_returns_full_chain(test_database_url):
    with psycopg.connect(test_database_url) as conn:
        row = conn.execute(
            "SELECT * FROM geo.locate_admin(%s, %s)",
            (CENTER["lng"], CENTER["lat"]),
        ).fetchone()

    assert row is not None
    assert row[0] == "32"          # province_code
    assert row[2] == "3273"        # regency_code
    assert row[4] == DISTRICT_CODE  # district_code
    assert row[6] == VILLAGE_CODE   # village_code
    assert row[9] == 4             # match_level
    assert row[10] is False        # is_approximate


def test_reverse_resolves_village_polygon_and_nearest_features(live_client):
    response = live_client.get(
        "/api/v1/geo/reverse",
        params={**CENTER, "refresh": "true"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert body["match"]["method"] == "polygon"
    assert body["match"]["level"] == 4
    assert body["match"]["approximate"] is False
    assert body["match"]["confidence"] >= 0.9

    assert body["region"]["province"] == {"code": "32", "name": "JAWA BARAT"}
    assert body["region"]["regency"] == {"code": "3273", "name": "BANDUNG"}
    assert body["region"]["district"]["code"] == DISTRICT_CODE
    assert body["region"]["village"]["code"] == VILLAGE_CODE

    assert body["address"]["postcode"] == "40236"
    assert "CIBADUYUT" in body["address"]["formatted"]
    assert body["nearest"]["place"]["name"] == "Cibaduyut"
    assert response.headers["cache-control"] == "public, max-age=3600"


def test_reverse_mampang_prapatan_iv_matches_bps(live_client):
    response = live_client.get(
        "/api/v1/geo/reverse", params={**MAMPANG_IV, "refresh": "true"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["match"]["method"] == "polygon"
    assert body["match"]["level"] == 4
    assert body["region"]["province"] == {"code": "31", "name": "DKI JAKARTA"}
    assert body["region"]["regency"] == {"code": "3171", "name": "JAKARTA SELATAN"}
    assert body["region"]["district"] == {"code": "3171070", "name": "MAMPANG PRAPATAN"}
    assert body["region"]["village"] == {"code": "3171070002", "name": "PELA MAMPANG"}
    assert body["address"]["postcode"] == "12720"
    assert body["nearest"]["road"]["name"] == "Jalan Mampang Prapatan IV"


def test_reverse_wisma_mulia_2_matches_bps(live_client):
    response = live_client.get(
        "/api/v1/geo/reverse", params={**WISMA_MULIA_2, "refresh": "true"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["match"]["method"] == "polygon"
    assert body["match"]["level"] == 4
    assert body["region"]["district"] == {"code": "3171070", "name": "MAMPANG PRAPATAN"}
    assert body["region"]["village"] == {"code": "3171070005", "name": "KUNINGAN BARAT"}
    assert body["address"]["postcode"] == "12950"
    assert body["nearest"]["place"]["name"] == "Wisma Mulia 2"
    assert body["nearest"]["road"]["name"] == "Jalan Jenderal Gatot Subroto"


def test_reverse_uses_database_cache_on_second_call(live_client, test_database_url):
    from app import cache

    # Start from a clean slate so the test does not depend on previous runs.
    key = cache.make_key(
        "reverse", {"lat": round(CENTER["lat"], 5), "lng": round(CENTER["lng"], 5)}
    )
    with psycopg.connect(test_database_url) as conn:
        conn.execute("DELETE FROM geo.geocode_cache WHERE cache_key = %s", (key,))
        conn.commit()
    cache._L1.clear()

    first = live_client.get("/api/v1/geo/reverse", params=CENTER)
    assert first.status_code == 200
    assert first.json().get("cached") is not True

    # Drop the process-local L1 entry: the next hit must come from PostGIS.
    cache._L1.clear()
    second = live_client.get("/api/v1/geo/reverse", params=CENTER)
    assert second.status_code == 200
    assert second.json().get("cached") is True


def test_reverse_rejects_coordinates_outside_indonesia(live_client):
    response = live_client.get(
        "/api/v1/geo/reverse", params={"lat": 51.5, "lng": -0.12}
    )
    assert response.status_code == 422


def test_search_ranks_exact_region_and_place(live_client):
    response = live_client.get("/api/v1/geo/search", params={"q": "Cibaduyut"})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 2
    assert body["results"][0]["kind"] == "region"
    assert body["results"][0]["id"] == VILLAGE_CODE
    assert body["results"][0]["score"] == 1.0
    assert any(item["kind"] == "place" for item in body["results"])
    assert body["took_ms"] >= 0


def test_search_can_include_village_geometry(live_client):
    response = live_client.get(
        "/api/v1/geo/search",
        params={"q": "Cibaduyut", "include_geometry": "true", "limit": 1},
    )

    assert response.status_code == 200
    geometry = response.json()["results"][0]["geometry"]
    assert geometry is not None
    assert geometry["type"] in {"Polygon", "MultiPolygon"}


def test_search_filters_by_kind(live_client):
    response = live_client.get(
        "/api/v1/geo/search", params={"q": "Bandung", "type": "place"}
    )
    assert response.status_code == 200
    assert all(item["kind"] == "place" for item in response.json()["results"])


def test_region_detail_contains_ancestors(live_client):
    response = live_client.get(f"/api/v1/geo/regions/{VILLAGE_CODE}")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "CIBADUYUT"
    assert body["level"] == 4
    assert body["full_name"] == "CIBADUYUT, BOJONGLOA KIDUL, BANDUNG, JAWA BARAT"
    assert [ancestor["level"] for ancestor in body["ancestors"]] == [1, 2, 3]
    assert [ancestor["code"] for ancestor in body["ancestors"]] == [
        "32",
        "3273",
        DISTRICT_CODE,
    ]


def test_region_detail_404(live_client):
    response = live_client.get("/api/v1/geo/regions/9999999999")
    assert response.status_code == 404


def test_region_boundary_returns_feature(live_client):
    response = live_client.get(f"/api/v1/geo/regions/{DISTRICT_CODE}/boundary")

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "Feature"
    assert body["id"] == DISTRICT_CODE
    assert body["properties"]["level"] == 3
    assert body["geometry"]["type"] in {"Polygon", "MultiPolygon"}


def test_region_boundary_404_for_unknown_region(live_client):
    response = live_client.get("/api/v1/geo/regions/9999999999/boundary")
    assert response.status_code == 404


def test_hierarchy_returns_nested_tree(live_client):
    response = live_client.get(
        "/api/v1/geo/regions/hierarchy", params={"level": 1, "depth": 3}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["count"] >= 2
    assert body["meta"]["nodes"] >= 8
    provinces = {item["code"]: item for item in body["data"]}
    assert {"31", "32"} <= set(provinces)
    assert provinces["32"]["children"]
    assert provinces["32"]["children"][0]["code"] == "3273"


def test_client_config_is_live(live_client):
    response = live_client.get("/api/v1/geo/config")
    assert response.status_code == 200
    assert response.json()["center"] == {"lat": -2.5, "lng": 118.0}
