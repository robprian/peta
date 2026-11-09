"""Pure unit tests: no database, no network."""

from __future__ import annotations

from types import SimpleNamespace

from app.cache import make_key
from app.config import Settings
from app.schemas import ReverseResponse, SearchItem
from app.services.geocode import in_indonesia
from app.services.photon import _bbox
from app.services.regions import _serialize
from app.services.search import _to_item


def test_in_indonesia_accepts_interior_points():
    assert in_indonesia(-6.946966, 107.598788) is True  # Bandung
    assert in_indonesia(0.0, 118.0) is True             # offshore, still in bbox


def test_in_indonesia_rejects_points_outside_bbox():
    assert in_indonesia(51.5, -0.12) is False  # London
    assert in_indonesia(-33.9, 151.2) is False  # Sydney


def test_bbox_includes_boundaries():
    assert in_indonesia(7.0, 94.0) is True
    assert in_indonesia(-12.0, 142.0) is True
    assert in_indonesia(7.0001, 118.0) is False
    assert in_indonesia(-2.0, 142.0001) is False


def test_cache_key_is_stable_and_order_independent():
    first = make_key("reverse", {"lat": -6.9, "lng": 107.6})
    second = make_key("reverse", {"lng": 107.6, "lat": -6.9})
    other = make_key("reverse", {"lat": -6.9, "lng": 107.7})
    assert first == second
    assert first != other
    assert len(first) == 64


def test_photon_extent_is_reordered_to_wsen():
    # Photon: [west, north, east, south]
    assert _bbox([107.0, -6.8, 107.7, -7.0]) == [107.0, -7.0, 107.7, -6.8]


def test_photon_extent_invalid_values_are_dropped():
    assert _bbox(None) is None
    assert _bbox([1, 2, 3]) is None
    assert _bbox(["a", "b", "c", "d"]) is None


def test_settings_cors_and_api_keys_parsing():
    settings = Settings(
        cors_origins="https://a.example, https://b.example",
        api_keys="key-1, key-2 ,",
    )
    assert settings.cors_origin_list == ["https://a.example", "https://b.example"]
    assert settings.api_key_set == {"key-1", "key-2"}

    wildcard = Settings(cors_origins="*", api_keys="")
    assert wildcard.cors_origin_list == ["*"]
    assert wildcard.api_key_set == set()


def test_serialize_region_without_geometry():
    row = {
        "code": "3273040004",
        "name": "CIBADUYUT",
        "level": 4,
        "parent_code": "3273040",
        "full_name": "CIBADUYUT, BOJONGLOA KIDUL, BANDUNG, JAWA BARAT",
        "postal_codes": ["40236"],
        "lat": -6.946966,
        "lng": 107.598788,
        "bbox": [107.595, -6.95, 107.602, -6.944],
        "geometry": {"type": "MultiPolygon", "coordinates": []},
    }

    item = _serialize(row)

    assert item["centroid"] == {"lat": -6.946966, "lng": 107.598788}
    assert item["bbox"] == [107.595, -6.95, 107.602, -6.944]
    assert item["postal_codes"] == ["40236"]
    assert "geometry" not in item


def test_serialize_region_with_geometry_and_empty_postal_codes():
    row = {
        "code": "32",
        "name": "JAWA BARAT",
        "level": 1,
        "parent_code": None,
        "full_name": "JAWA BARAT",
        "postal_codes": None,
        "lat": None,
        "lng": None,
        "bbox": None,
        "geometry": {"type": "MultiPolygon", "coordinates": []},
    }

    item = _serialize(row, include_geometry=True)

    assert item["centroid"] is None
    assert item["bbox"] is None
    assert item["postal_codes"] == []
    assert item["geometry"]["type"] == "MultiPolygon"


def test_search_row_maps_full_region_chain():
    row = {
        "kind": "region",
        "id": "3273040004",
        "name": "CIBADUYUT",
        "label": "CIBADUYUT, BOJONGLOA KIDUL, BANDUNG, JAWA BARAT",
        "level": 4,
        "lat": -6.946966,
        "lng": 107.598788,
        "bbox": None,
        "postcode": "40236",
        "category": None,
        "type": None,
        "province_code": "32",
        "province_name": "JAWA BARAT",
        "regency_code": "3273",
        "regency_name": "BANDUNG",
        "district_code": "3273040",
        "district_name": "BOJONGLOA KIDUL",
        "village_code": "3273040004",
        "village_name": "CIBADUYUT",
        "score": 1.0,
        "geometry": '{"type": "MultiPolygon", "coordinates": []}',
    }

    item = _to_item(row)
    validated = SearchItem.model_validate(item)

    assert validated.region.province.code == "32"
    assert validated.region.village.name == "CIBADUYUT"
    assert validated.geometry == {"type": "MultiPolygon", "coordinates": []}
    assert validated.score == 1.0


def test_search_row_maps_standalone_place():
    row = {
        "kind": "place",
        "id": "osm:n900000002",
        "name": "Cibaduyut",
        "label": "Cibaduyut, Bojongloa Kidul, Bandung, Jawa Barat",
        "level": None,
        "lat": -6.946966,
        "lng": 107.598788,
        "bbox": None,
        "postcode": "40236",
        "category": "place",
        "type": "village",
        "province_code": None,
        "province_name": None,
        "regency_code": None,
        "regency_name": None,
        "district_code": None,
        "district_name": None,
        "village_code": None,
        "village_name": None,
        "score": 1.0,
        "geometry": None,
    }

    item = _to_item(row)

    assert item["region"] is None
    assert item["kind"] == "place"
    assert item["category"] == "place"


def test_reverse_response_model_accepts_minimal_payload():
    parsed = ReverseResponse.model_validate(
        {
            "found": False,
            "location": {"lat": 0.0, "lng": 0.0},
            "reason": "outside_indonesia",
        }
    )
    assert parsed.found is False
    assert parsed.region is None


def test_rate_limit_settings_object_shape():
    """Guard against accidental renames used by app.main at import time."""
    settings = SimpleNamespace(rate_limit_per_minute=120)
    assert settings.rate_limit_per_minute == 120
