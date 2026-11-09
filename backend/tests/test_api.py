"""HTTP contract tests with service calls mocked (no database required)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import geo as geo_api
from app.main import app as fastapi_app


@pytest.fixture()
def health_ok(monkeypatch):
    mock = AsyncMock(
        return_value={
            "postgis_version": "3.4 USE_GEOS=1 USE_PROJ=1",
            "db_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }
    )
    monkeypatch.setattr("app.main.healthcheck", mock)
    return mock


def test_health_reports_database_and_postgis(client, health_ok):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"
    assert "3.4" in body["postgis"]
    assert body["version"] == fastapi_app.version
    health_ok.assert_awaited_once()


def test_health_degrades_when_database_is_down(client, monkeypatch):
    monkeypatch.setattr(
        "app.main.healthcheck", AsyncMock(side_effect=RuntimeError("connection refused"))
    )
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_client_config_exposes_widget_defaults(client):
    response = client.get("/api/v1/geo/config")
    assert response.status_code == 200
    body = response.json()
    assert body["country"] == "ID"
    assert body["bbox"] == [94.0, -12.0, 142.0, 7.0]
    assert [level["code_length"] for level in body["levels"]] == [2, 4, 7, 10]


def test_observability_headers_and_request_id_propagation(client):
    response = client.get("/api/v1/geo/config", headers={"X-Request-ID": "abc123"})
    assert response.headers["X-Request-ID"] == "abc123"
    assert response.headers["X-Response-Time"].endswith("ms")


def test_cors_preflight_allows_configured_origins(client):
    response = client.options(
        "/api/v1/geo/reverse",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] in {"*", "https://example.com"}


def test_reverse_requires_coordinates(client):
    assert client.get("/api/v1/geo/reverse").status_code == 422


def test_reverse_rejects_invalid_latitude(client):
    response = client.get("/api/v1/geo/reverse", params={"lat": 91, "lng": 107})
    assert response.status_code == 422


def test_reverse_rejects_coordinates_outside_indonesia(client, monkeypatch):
    mocked = AsyncMock()
    monkeypatch.setattr(geo_api.geocode, "reverse_geocode", mocked)

    response = client.get("/api/v1/geo/reverse", params={"lat": 51.5, "lng": -0.12})

    assert response.status_code == 422
    assert "Indonesia" in response.json()["detail"]
    mocked.assert_not_awaited()


def test_reverse_success_sets_cache_header(client, monkeypatch):
    payload = {
        "found": True,
        "location": {"lat": -6.946966, "lng": 107.598788},
        "source": "postgis+osm",
    }
    mocked = AsyncMock(return_value=payload)
    monkeypatch.setattr(geo_api.geocode, "reverse_geocode", mocked)

    response = client.get(
        "/api/v1/geo/reverse",
        params={"lat": -6.946966, "lng": 107.598788},
    )

    assert response.status_code == 200
    assert response.json()["found"] is True
    assert response.headers["cache-control"] == "public, max-age=3600"
    mocked.assert_awaited_once_with(-6.946966, 107.598788, use_cache=True)


def test_reverse_refresh_bypasses_cache(client, monkeypatch):
    mocked = AsyncMock(
        return_value={
            "found": True,
            "location": {"lat": -6.9, "lng": 107.6},
        }
    )
    monkeypatch.setattr(geo_api.geocode, "reverse_geocode", mocked)

    response = client.get(
        "/api/v1/geo/reverse",
        params={"lat": -6.9, "lng": 107.6, "refresh": "true"},
    )

    assert response.status_code == 200
    mocked.assert_awaited_once_with(-6.9, 107.6, use_cache=False)


def test_reverse_not_found_is_not_cached(client, monkeypatch):
    monkeypatch.setattr(
        geo_api.geocode,
        "reverse_geocode",
        AsyncMock(
            return_value={
                "found": False,
                "reason": "outside_indonesia",
                "location": {"lat": -5.0, "lng": 120.0},
            }
        ),
    )

    response = client.get("/api/v1/geo/reverse", params={"lat": -5.0, "lng": 120.0})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_search_success(client, monkeypatch):
    results = [
        {
            "id": "3273040004",
            "kind": "region",
            "name": "CIBADUYUT",
            "label": "CIBADUYUT, BOJONGLOA KIDUL, BANDUNG, JAWA BARAT",
            "level": 4,
            "lat": -6.946966,
            "lng": 107.598788,
            "score": 1.0,
        }
    ]
    monkeypatch.setattr(
        geo_api.search, "search_places", AsyncMock(return_value=(results, 4.2))
    )

    response = client.get("/api/v1/geo/search", params={"q": "Cibaduyut"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Cibaduyut"
    assert body["count"] == 1
    assert body["took_ms"] == 4.2
    assert body["results"][0]["kind"] == "region"
    assert response.headers["cache-control"] == "public, max-age=60"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "a", "limit": 0},
        {"q": "a", "limit": 21},
        {"q": "a", "type": "invalid"},
    ],
)
def test_search_validates_query_parameters(client, params):
    assert client.get("/api/v1/geo/search", params=params).status_code == 422


def test_region_detail_returns_item(client, monkeypatch):
    item = {
        "code": "32",
        "name": "JAWA BARAT",
        "level": 1,
        "parent_code": None,
        "full_name": "JAWA BARAT",
        "postal_codes": [],
        "centroid": {"lat": -6.9, "lng": 107.6},
        "bbox": None,
        "ancestors": [],
    }
    mocked = AsyncMock(return_value=item)
    monkeypatch.setattr(geo_api.regions, "get_region", mocked)

    response = client.get("/api/v1/geo/regions/32")

    assert response.status_code == 200
    assert response.json()["code"] == "32"
    mocked.assert_awaited_once_with("32", include_geometry=False)


def test_region_detail_404(client, monkeypatch):
    monkeypatch.setattr(geo_api.regions, "get_region", AsyncMock(return_value=None))
    response = client.get("/api/v1/geo/regions/9999999999")
    assert response.status_code == 404


def test_region_boundary_returns_feature(client, monkeypatch):
    feature = {
        "type": "Feature",
        "id": "3273040",
        "properties": {"code": "3273040", "name": "BOJONGLOA KIDUL", "level": 3},
        "geometry": {"type": "Polygon", "coordinates": []},
    }
    monkeypatch.setattr(
        geo_api.regions, "get_boundary", AsyncMock(return_value=feature)
    )

    response = client.get("/api/v1/geo/regions/3273040/boundary")

    assert response.status_code == 200
    assert response.json()["geometry"]["type"] == "Polygon"


def test_region_boundary_404_for_village_without_polygon(client, monkeypatch):
    monkeypatch.setattr(geo_api.regions, "get_boundary", AsyncMock(return_value=None))
    response = client.get("/api/v1/geo/regions/3273040001/boundary")
    assert response.status_code == 404


def test_region_boundary_validates_simplify(client):
    response = client.get(
        "/api/v1/geo/regions/3273040/boundary", params={"simplify": 0.5}
    )
    assert response.status_code == 422


def test_hierarchy_returns_tree(client, monkeypatch):
    tree = [
        {
            "code": "32",
            "name": "JAWA BARAT",
            "level": 1,
            "parent_code": None,
            "full_name": "JAWA BARAT",
            "postal_codes": [],
            "centroid": None,
            "bbox": None,
            "children": [
                {
                    "code": "3273",
                    "name": "BANDUNG",
                    "level": 2,
                    "parent_code": "32",
                    "children": [],
                }
            ],
        }
    ]
    meta = {"count": 1, "nodes": 2, "depth": 1}
    mocked = AsyncMock(return_value=(tree, meta))
    monkeypatch.setattr(geo_api.regions, "get_hierarchy", mocked)

    response = client.get("/api/v1/geo/regions/hierarchy", params={"level": 1})

    assert response.status_code == 200
    assert response.json()["meta"] == meta
    assert response.json()["data"][0]["children"][0]["code"] == "3273"


@pytest.mark.parametrize(
    "params",
    [
        {"level": 0},
        {"level": 5},
        {"depth": 5},
        {"limit": 0},
        {"limit": 501},
        {"code": "abc"},
    ],
)
def test_hierarchy_validates_parameters(client, params):
    assert client.get("/api/v1/geo/regions/hierarchy", params=params).status_code == 422


def _install_api_key(monkeypatch):
    monkeypatch.setattr(
        geo_api,
        "get_settings",
        lambda: SimpleNamespace(api_key_set={"secret-key"}),
    )


def test_api_key_guard_rejects_missing_key(client, monkeypatch):
    _install_api_key(monkeypatch)
    response = client.get("/api/v1/geo/regions/32")
    assert response.status_code == 401


def test_api_key_guard_rejects_wrong_key(client, monkeypatch):
    _install_api_key(monkeypatch)
    response = client.get(
        "/api/v1/geo/regions/32", headers={"X-API-Key": "wrong"}
    )
    assert response.status_code == 401


def test_api_key_guard_accepts_header(client, monkeypatch):
    _install_api_key(monkeypatch)
    monkeypatch.setattr(
        geo_api.regions,
        "get_region",
        AsyncMock(
            return_value={
                "code": "32",
                "name": "JAWA BARAT",
                "level": 1,
                "ancestors": [],
            }
        ),
    )
    response = client.get(
        "/api/v1/geo/regions/32", headers={"X-API-Key": "secret-key"}
    )
    assert response.status_code == 200


def test_api_key_guard_accepts_query_parameter(client, monkeypatch):
    _install_api_key(monkeypatch)
    monkeypatch.setattr(
        geo_api.regions,
        "get_region",
        AsyncMock(
            return_value={
                "code": "32",
                "name": "JAWA BARAT",
                "level": 1,
                "ancestors": [],
            }
        ),
    )
    response = client.get("/api/v1/geo/regions/32", params={"api_key": "secret-key"})
    assert response.status_code == 200
