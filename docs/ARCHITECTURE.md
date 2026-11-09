# Architecture

Peta Indonesia is a self-contained geocoding stack: a PostGIS schema, an ETL
pipeline for BPS/Kemendagri boundaries and Geofabrik OpenStreetMap, a FastAPI
service, and an embeddable Leaflet widget.

```text
                         +-----------------------------+
  BPS CSV + GeoJSON ---> |  etl/import_admin.py        | --+
                         +-----------------------------+   |
                                                           |    +----------------------+
  Geofabrik .osm.pbf --> |  osmium tags-filter/export  |   +--> | PostgreSQL + PostGIS |
                         |  etl/import_osm.py          | --+    | schema: geo          |
                         +-----------------------------+        +----------+-----------+
                                                                           |
                                     +-------------------------------------+
                                     |  FastAPI (async psycopg pool)       |
                                     |  /reverse /search /regions ...      |
                                     +------------------+------------------+
                                                        |
                              +-------------------------+-----------------------+
                              |                                                 |
                    Leaflet widget (iframe)                          Your application
                    postMessage <--> parent                          React / Web Component
```

## 1. Components

| Component | Path | Responsibility |
| --- | --- | --- |
| Schema | `migrations/001_schema.sql` | Tables, geometry columns, generated search vectors |
| Indexes | `migrations/002_indexes.sql` | GiST, GIN/trigram, hierarchy and cache indexes |
| SQL functions | `migrations/003_functions.sql` | `locate_admin`, `reverse_geocode`, `refresh_region_full_names` |
| Admin ETL | `etl/import_admin.py` | CSV attributes + BPS GeoJSON -> `geo.admin_regions` |
| OSM ETL | `etl/import_osm.py` | GeoJSONSeq from `osmium export` -> places/roads |
| OSM shell driver | `etl/run_osm_import.sh` | Filter, export, import, village centroid backfill |
| Village linker | `etl/link_osm_villages.sql` | Match village names to OSM place nodes inside districts |
| Demo seed | `etl/seed_demo.py` | Jakarta + Bandung BPS/OSM fixture for development and tests |
| API | `backend/app` | FastAPI routes, services, pool, cache, schemas |
| Widget | `frontend/widget/location-picker.html` | Standalone Leaflet UI and `postMessage` protocol |
| Wrappers | `frontend/embed`, `frontend/react` | Web Component and typed React component |

The API is stateless. All durable state lives in PostgreSQL; the in-process L1
cache is only an optimisation and is safe to lose on restart.

## 2. Data model

### 2.1 `geo.admin_regions` — one table for four levels

| Level | Entity | BPS code length | Example |
| --- | --- | --- | --- |
| 1 | Province (`provinsi`) | 2 | `32` Jawa Barat |
| 2 | Regency/city (`kabupaten/kota`) | 4 | `3273` Kota Bandung |
| 3 | District (`kecamatan`) | 7 | `3273040` Bojongloa Kidul |
| 4 | Village (`kelurahan/desa`) | 10 | `3273040004` Cibaduyut |

A single table keeps hierarchy queries, search and permissions uniform. The
level/code-length invariant is enforced by `admin_regions_level_code_chk`.

Key columns:

- `code` — BPS code without the country prefix, primary key.
- `parent_code` — self reference, deferrable so bulk inserts can arrive in any
  order within a transaction.
- `province_code`, `regency_code`, `district_code` — denormalised ancestors.
  Reverse geocoding and search avoid recursive joins on the hot path.
- `postal_codes text[]` — all postcodes observed for the region; the first value
  is used as the default address postcode.
- `geom` — authoritative `MultiPolygon` in EPSG:4326, validated with
  `ST_MakeValid` during import.
- `geom_simplified` — `ST_SimplifyPreserveTopology(geom, 0.0005)` for map
  payloads. Analysis always uses `geom`.
- `centroid`, `bbox`, `area_km2` — derived at import time. `bbox` is the
  envelope polygon used by the API to build `[west, south, east, north]`.
- `full_name` — recursive display name such as
  `CIBADUYUT, BOJONGLOA KIDUL, BANDUNG, JAWA BARAT`.
- `search_vector` — generated `tsvector` over `name` and `full_name`.
- `attrs jsonb`, `source`, `kemendagri_code` — provenance and future mappings.

Villages in the bundled BPS dataset have no geometry. They are still inserted
with attributes, postal codes and (optionally) centroids from CSV or OSM. The
reverse geocoder explicitly handles this partial coverage.

### 2.2 OSM tables

`geo.osm_places` stores POIs, settlements and addressable features:

- stable OSM identity via `(osm_type, osm_id)`;
- point geometry derived with `ST_PointOnSurface` for ways/relations;
- normalised address columns (`addr_street`, `addr_postcode`, `addr_city`, ...);
- `category`/`type` from the first matching OSM tag group;
- `importance`/`rank_search` for ranking;
- generated `search_vector` over `name` and `display_name`.

`geo.osm_roads` stores named road segments with `LineString`/`MultiLineString`
geometry. It powers the "nearest road" part of a reverse result. Roads are
matched by `osm_id`, so re-imports are idempotent.

`geo.postal_codes` and `geo.geocode_cache` are auxiliary. `geo.import_runs`
records every ETL execution with status, row count and failure notes.

## 3. Administrative boundary ETL

Input layout (the repository ships country code `62`):

```text
data/csv/62/{provinces,cities,subDistricts,villages}.csv
data/geojson/62/<province>/<regency>/<district>.json
```

`etl/import_admin.py`:

1. Reads CSV attributes with `csv.DictReader` and normalises postcodes to a
   sorted `text[]` of five-digit values.
2. Derives parent/ancestor codes. Regency and district ancestors are resolved
   from the CSV, with the code prefix as a fallback.
3. Indexes GeoJSON files by filename (`<code>.json`) for levels 1–3, reads the
   first feature's geometry, and wraps it with `ST_Multi(ST_CollectionExtract(
   ST_MakeValid(...), 3))`.
4. Computes `geom_simplified`, `centroid` (polygon point-on-surface, else CSV
   coordinates), `bbox` and `area_km2` inside PostgreSQL.
5. Upserts in batches. If a batch fails, each row is retried; if geometry is the
   cause, the row is imported without geometry so attributes are never lost.
6. Calls `geo.refresh_region_full_names()` and `ANALYZE` after a complete run.

Partial imports are supported with `--province 32`. Use `--no-geometry` for a
fast attribute-only load and `--village-centroids file.csv` for externally
computed village points.

Command:

```bash
python etl/import_admin.py \
  --data-dir data \
  --database-url "$DATABASE_URL" \
  --province 32
```

### Village coverage

The source GeoJSON stops at district level. Two backfills are provided:

- `etl/import_admin.py --village-centroids csv` for an authoritative point CSV;
- `etl/link_osm_villages.sql`, which matches `place=village/hamlet/suburb/...`
  OSM nodes by name inside the parent district polygon.

Villages without a polygon are resolved by nearest-centroid fallback in
`geo.locate_admin()`; the response is marked `approximate=true`. A point that
falls inside a district polygon but not inside a village polygon still reports
the full province/regency/district chain.

## 4. OpenStreetMap ETL

The shell driver runs four stages:

```bash
bash etl/run_osm_import.sh indonesia-latest.osm.pbf
```

```text
1. osmium tags-filter   keep places, amenities, shops, tourism, offices,
                        healthcare, leisure, historic, addresses, highways
2. osmium export        GeoJSONSeq, geometry types point/linestring/polygon
3. import_osm.py        classify -> geo.osm_places / geo.osm_roads
4. link_osm_villages.sql backfill village centroids from place nodes
```

`import_osm.py` streams one feature per line, so the 1.7 GB PBF is never loaded
into memory. It deduplicates by OSM id inside each batch and upserts, making
retries safe. Features without a name and category are skipped. Address-only
features become `category='address'` places.

For very large or frequently refreshed extracts, `osm2pgsql` with a flex style
can replace stage 3. The API only depends on the two table contracts above.

## 5. Reverse geocoding

`GET /api/v1/geo/reverse` performs one database round-trip:

1. Validate coordinates against the Indonesia bounding box
   `94..142 E, -12..7 S` in the API layer.
2. `geo.locate_admin(lng, lat)`:
   - find the deepest polygon containing the point (`ST_Covers`), ordered by
     level descending and area ascending;
   - if no polygon contains it, find a polygon within 25 km and mark the result
     approximate;
   - walk `parent_code` upward to complete the province/regency/district/village
     chain;
   - fill missing levels with the nearest centroid in the appropriate parent,
     marking `is_approximate`.
3. `geo.reverse_geocode(lat, lng)` additionally finds:
   - the nearest named road within 250 m;
   - the nearest named place/POI within 300 m;
   - a postcode (POI address first, then region postal array);
   - a formatted address and a human label.
4. The Python service optionally enriches empty street/housenumber fields from
   Nominatim when `NOMINATIM_URL` is configured. PostGIS data always wins.

Confidence is deterministic: `0.98` for a village polygon, `0.80` for an
approximate village, `0.65` for district-only, `0.50` for regency-only, and
`0.30` for province-only matches.

## 6. Forward geocoding and autocomplete

`GET /api/v1/geo/search` runs a single SQL statement with two candidate sets:

- administrative regions, matched by trigram similarity, prefix/ILIKE,
  full-text search, or BPS code prefix;
- OSM places, matched by trigram similarity, prefix/ILIKE or full-text search.

Each candidate gets a `match_rank` (exact name, name prefix, full-name
substring, full-text, fuzzy) and a similarity score. Results are ordered by
rank, score, then regions before places. Candidate sets are bounded
(`limit * 8`, minimum 40) before the final `LIMIT`, keeping latency predictable
on 80k+ regions and millions of OSM rows.

If fewer than `limit` local results are found and `PHOTON_URL` is set, the
service queries Photon with an Indonesia bounding box and de-duplicates by
name/coordinate. Local PostGIS results keep priority.

## 7. Caching, timeouts and indexes

- L1: per-process dictionary, 5-minute TTL, 1024 entries.
- L2: `geo.geocode_cache`, JSONB payload with configurable TTL
  (`CACHE_TTL_SECONDS`, default 24 h). Reverse lookups are cached only when
  `found=true`; `refresh=true` bypasses both layers.
- HTTP: reverse responses set `Cache-Control: public, max-age=3600` on hits and
  `no-store` on misses; search sets `max-age=60`; hierarchy sets `max-age=3600`.
- `statement_timeout` defaults to 5 s per connection.
- GiST indexes cover `geom`, `geom_simplified`, `centroid`, OSM points and
  roads; GIN/trigram indexes cover names, `full_name`, generated tsvectors and
  postal arrays.

## 8. Deployment

`docker-compose.yml` starts PostGIS 16-3.4 and the API. The API image is a
multi-stage-free `python:3.12-slim` build; the runtime runs as an unprivileged
user and includes a health check. CORS, optional API keys and rate limits are
environment-driven. See `docs/API.md` and the root `README.md`.

## 9. Scaling notes

- Partition `admin_regions` and `osm_places` by province once the dataset grows
  beyond a single node's comfortable working set; the denormalised
  `province_code` is already present for partition pruning.
- Use `osm2pgsql` flex or impose/expire from a minutely diff for fresh OSM data.
- Serve simplified boundaries as vector tiles (Martin/pg_tileserv) instead of
  GeoJSON once clients request many polygons.
- Run `VACUUM (ANALYZE)` after bulk loads; the ETL already runs `ANALYZE`.
- Add read replicas for search traffic; reverse lookups can be routed to the
  primary only when cache misses matter.

## 10. Validation status and limitations

Validated against a real `postgis/postgis:16-3.4` instance:

- all migrations apply cleanly;
- demo reverse geocoding resolves province -> village at polygon level, nearest
  road/POI and formatted address;
- search ranks exact region and OSM place matches correctly;
- hierarchy, detail, boundary and API auth/error contracts are covered by 60
  automated tests (unit + integration);
- a real partial import of province 32 loaded 6,618 regions from 654 GeoJSON
  files, and a sample OSM extract exercised places, roads and the village
  centroid linker end to end.

Known limitations:

- The bundled BPS GeoJSON has no village polygons; village-level `geom` is
  therefore null unless supplied externally.
- The full 1.7 GB PBF and 653 MB GeoJSON have not been imported in this
  workspace; the ETL is validated on the demo fixture and designed for partial
  province imports.
- Nominatim/Photon are optional external dependencies and are disabled by
  default.
- OSM data quality varies; `nearest` results are best-effort and always
  accompanied by distance and match metadata.


