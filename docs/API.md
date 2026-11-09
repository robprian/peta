# API Reference

Base URL: `http://localhost:8000` (development) or your deployment host.

Interactive docs: `/docs` (Swagger UI) and `/redoc`.

## Authentication and limits

Authentication is optional. If `API_KEYS` is empty, every request is allowed.
Otherwise send one of:

```http
X-API-Key: your-key
```

or `?api_key=your-key`. All `/api/v1/geo/*` routes are protected; `/health`
and `/api/v1/geo/config` are public.

Rate limiting defaults to 120 requests/minute per client address
(`RATE_LIMIT_PER_MINUTE`). Every response includes `X-Request-ID` and
`X-Response-Time`. CORS origins are configured with `CORS_ORIGINS` (comma
separated, or `*`).

Errors use FastAPI's standard shape:

```json
{ "detail": "Koordinat di luar bounding box Indonesia (94..142 BT, -12..7 LS)." }
```

| Status | Meaning |
| --- | --- |
| 200 | Success |
| 401 | Missing/invalid API key |
| 404 | Region or boundary not found |
| 422 | Invalid parameter or coordinate outside Indonesia |
| 429 | Rate limit exceeded |
| 503 | Database unavailable (`/health`) |

## `GET /health`

Liveness/readiness probe. Returns PostGIS version and database time.

```json
{
  "status": "ok",
  "database": "up",
  "postgis": "3.4 USE_GEOS=1 USE_PROJ=1",
  "db_time": "2026-11-09T04:12:50.123456+00:00",
  "version": "1.0.0"
}
```

Returns `503` with `status: "degraded"` when the pool cannot query the database.

## `GET /api/v1/geo/config`

Public widget configuration: country, bounding box, default center/zoom, tile
URL/attribution and the four administrative levels. No database access.

## `GET /api/v1/geo/reverse`

Resolve a coordinate to the administrative hierarchy, nearest road/POI and a
formatted address.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `lat` | float | yes | Latitude, -90..90 |
| `lng` | float | yes | Longitude, -180..180 |
| `refresh` | bool | no | Bypass L1 and database cache |

Coordinates outside `94..142 E, -12..7 S` return `422` before touching the
database.

Example:

```bash
curl 'http://localhost:8000/api/v1/geo/reverse?lat=-6.946966&lng=107.598788'
```

```json
{
  "found": true,
  "location": { "lat": -6.946966, "lng": 107.598788 },
  "region": {
    "province": { "code": "32", "name": "JAWA BARAT" },
    "regency": { "code": "3273", "name": "BANDUNG" },
    "district": { "code": "3273040", "name": "BOJONGLOA KIDUL" },
    "village": { "code": "3273040004", "name": "CIBADUYUT" }
  },
  "address": {
    "line1": "Jalan Cibaduyut",
    "street": "Jalan Cibaduyut",
    "housenumber": null,
    "village": "CIBADUYUT",
    "district": "BOJONGLOA KIDUL",
    "regency": "BANDUNG",
    "province": "JAWA BARAT",
    "postcode": "40236",
    "formatted": "Jalan Cibaduyut, CIBADUYUT, BOJONGLOA KIDUL, BANDUNG, JAWA BARAT, 40236",
    "label": "Cibaduyut, Bojongloa Kidul, Bandung, Jawa Barat"
  },
  "nearest": {
    "road": {
      "name": "Jalan Cibaduyut",
      "ref": null,
      "highway": "residential",
      "distance_m": 63.0
    },
    "place": {
      "name": "Cibaduyut",
      "category": "place",
      "type": "village",
      "lat": -6.946966,
      "lon": 107.598788,
      "distance_m": 0.0
    }
  },
  "match": {
    "method": "polygon",
    "level": 4,
    "approximate": false,
    "distance_m": 0.0,
    "confidence": 0.98
  },
  "source": "postgis+osm",
  "cached": true
}
```

`match.method` is `polygon` when the coordinate is inside a polygon,
`nearest` when a fallback was used, and `none` when nothing was resolved.
`match.approximate` is the reliable signal for village-centroid fallback.

## `GET /api/v1/geo/search`

Autocomplete and forward geocoding across administrative regions and OSM
places.

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `q` | string | required | 1..200 characters |
| `limit` | int | 5 | 1..20 |
| `type` | enum | `all` | `all`, `region`, or `place` |
| `include_geometry` | bool | false | Include simplified region polygon (larger payload) |

```bash
curl 'http://localhost:8000/api/v1/geo/search?q=Cibaduyut&limit=3'
```

```json
{
  "query": "Cibaduyut",
  "count": 3,
  "results": [
    {
      "id": "3273040004",
      "kind": "region",
      "name": "CIBADUYUT",
      "label": "CIBADUYUT, BOJONGLOA KIDUL, BANDUNG, JAWA BARAT",
      "level": 4,
      "lat": -6.946966,
      "lng": 107.598788,
      "bbox": [107.595, -6.95, 107.602, -6.944],
      "postcode": "40236",
      "category": null,
      "type": null,
      "region": {
        "province": { "code": "32", "name": "JAWA BARAT" },
        "regency": { "code": "3273", "name": "BANDUNG" },
        "district": { "code": "3273040", "name": "BOJONGLOA KIDUL" },
        "village": { "code": "3273040004", "name": "CIBADUYUT" }
      },
      "score": 1.0,
      "geometry": null
    },
    {
      "id": "osm:n900000002",
      "kind": "place",
      "name": "Cibaduyut",
      "label": "Cibaduyut, Bojongloa Kidul, Bandung, Jawa Barat",
      "level": null,
      "lat": -6.946966,
      "lng": 107.598788,
      "bbox": null,
      "postcode": "40236",
      "category": "place",
      "type": "village",
      "region": null,
      "score": 1.0,
      "geometry": null
    }
  ],
  "took_ms": 13.48
}
```

Use `id` for selection; `kind` distinguishes a BPS region from an OSM feature.
OSM ids have the form `osm:<type><id>` (for example `osm:n900000002`). When
`include_geometry` is true, region results contain a simplified GeoJSON
`MultiPolygon` for the boundary overlay.

## `GET /api/v1/geo/regions/hierarchy`

Nested administrative tree. With no filter it returns provinces only.

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `code` | string | — | Exact BPS code (2–13 digits) |
| `parent_code` | string | — | Direct children of a region |
| `level` | int | — | 1..4 |
| `depth` | int | 1 | How many child levels to include (0..4) |
| `q` | string | — | Filter roots by name/full name |
| `limit` | int | 50 | Root rows, 1..500 |
| `offset` | int | 0 | Pagination of roots |
| `include_geometry` | bool | false | Include simplified polygons |

```bash
curl 'http://localhost:8000/api/v1/geo/regions/hierarchy?level=1&depth=3'
```

Response:

```json
{
  "data": [
    {
      "code": "32",
      "name": "JAWA BARAT",
      "level": 1,
      "parent_code": null,
      "full_name": "JAWA BARAT",
      "postal_codes": ["40100", "40200"],
      "centroid": { "lat": -6.9033, "lng": 107.6426 },
      "bbox": [107.5, -7.0, 107.75, -6.85],
      "children": [
        {
          "code": "3273",
          "name": "BANDUNG",
          "level": 2,
          "parent_code": "32",
          "children": []
        }
      ]
    }
  ],
  "meta": {
    "count": 1,
    "nodes": 8,
    "depth": 3,
    "level": 1,
    "parent_code": null,
    "q": null,
    "limit": 50,
    "offset": 0
  }
}
```

`meta.count` counts roots; `meta.nodes` counts every node in the returned tree.

## `GET /api/v1/geo/regions/{code}`

Region attributes plus the ordered ancestor chain.

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `code` | path | required | BPS code |
| `include_geometry` | bool | false | Include simplified polygon |

```bash
curl 'http://localhost:8000/api/v1/geo/regions/3273040004'
```

```json
{
  "code": "3273040004",
  "name": "CIBADUYUT",
  "level": 4,
  "parent_code": "3273040",
  "full_name": "CIBADUYUT, BOJONGLOA KIDUL, BANDUNG, JAWA BARAT",
  "postal_codes": ["40236"],
  "centroid": { "lat": -6.946966, "lng": 107.598788 },
  "bbox": [107.595, -6.95, 107.602, -6.944],
  "ancestors": [
    { "code": "32", "name": "JAWA BARAT", "level": 1 },
    { "code": "3273", "name": "BANDUNG", "level": 2 },
    { "code": "3273040", "name": "BOJONGLOA KIDUL", "level": 3 }
  ]
}
```

Unknown codes return `404`.

## `GET /api/v1/geo/regions/{code}/boundary`

GeoJSON `Feature` for the region polygon.

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `code` | path | required | BPS code |
| `simplify` | float | 0.0005 | `ST_SimplifyPreserveTopology` tolerance in degrees, 0..0.1; `0` returns the full geometry |

```bash
curl 'http://localhost:8000/api/v1/geo/regions/3273040/boundary?simplify=0.0005'
```

```json
{
  "type": "Feature",
  "id": "3273040",
  "properties": {
    "code": "3273040",
    "name": "BOJONGLOA KIDUL",
    "level": 3,
    "full_name": "BOJONGLOA KIDUL, BANDUNG, JAWA BARAT",
    "postal_codes": ["40234", "40235", "40236", "40237", "40238", "40239"]
  },
  "geometry": { "type": "Polygon", "coordinates": [] }
}
```

Villages with only a centroid (no source polygon) return `404`. Clients should
fall back to the search result's `bbox`, `centroid` or the nearest boundary.

## Widget integration

The widget calls `/reverse`, `/search`, `/regions/*/boundary` and `/config`.
Its `postMessage` contract and payload examples are documented in
`frontend/README.md`. The important parent-side event is `LOCATION_SELECTED`;
the payload includes `lat`, `lng`, `address`, `region`, `postal_code`,
`formatted_address`, `nearest` and `match`.

## curl cheat sheet

```bash
# Reverse
curl 'http://localhost:8000/api/v1/geo/reverse?lat=-6.946966&lng=107.598788'

# Autocomplete with polygon overlay
curl 'http://localhost:8000/api/v1/geo/search?q=Cibaduyut&include_geometry=true'

# Children of a regency
curl 'http://localhost:8000/api/v1/geo/regions/hierarchy?parent_code=3273&depth=2'

# Village detail
curl 'http://localhost:8000/api/v1/geo/regions/3273040004'

# District boundary
curl 'http://localhost:8000/api/v1/geo/regions/3273040/boundary'

# With API key enabled
curl -H 'X-API-Key: secret' \
  'http://localhost:8000/api/v1/geo/reverse?lat=-6.946966&lng=107.598788'
```


