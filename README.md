# Peta Indonesia — GIS & Geocoding Platform

A production-oriented geocoding system for Indonesia: PostGIS boundaries for
the full BPS/Kemendagri hierarchy, OpenStreetMap POIs and roads, a FastAPI
service for reverse geocoding and autocomplete, and an embeddable Leaflet
location picker that reports its selection to the parent page via
`postMessage`.

The stack is self-hosted. No external geocoder is required; Nominatim and
Photon are optional enrichments.

## Live demo (GitHub Pages)

- Landing + interactive demo: <https://robprian.github.io/peta/>
- Widget: <https://robprian.github.io/peta/widget/location-picker.html?demo=1&lat=-6.946966&lng=107.598788&zoom=14>
- Embed/payload example: <https://robprian.github.io/peta/embed-example.html>

GitHub Pages hosts a **static** build only: `?demo=1` enables a small in-browser
adapter (`frontend/demo/demo-api.js`) backed by the Bandung fixture, so the map,
search, reverse geocoding and `LOCATION_SELECTED` flow work without a server.
The real FastAPI + PostgreSQL/PostGIS backend cannot run on Pages; deploy
`backend/` separately and pass `?apiBase=https://your-api.example.id` (without
`demo=1`) for full Indonesia coverage.

## Features

- **Reverse geocoding** at province, regency, district and village level.
- **Nearest road and POI** with distance, name and OSM classification.
- **Formatted address** with postcode, plus a human-readable label.
- **Autocomplete/search** over administrative regions and OSM places with
  trigram + full-text ranking.
- **Hierarchy API** for cascading province -> regency -> district -> village
  selects.
- **GeoJSON boundaries** with server-side simplification.
- **Embeddable widget**: standalone HTML, Web Component and typed React
  wrapper; works in an iframe and is responsive on mobile.
- **PostGIS-first performance**: GiST/GIN indexes, denormalised ancestors,
  two-layer cache, statement timeouts.
- **Idempotent ETL** for BPS CSV/GeoJSON and Geofabrik `.osm.pbf`.
- **60 automated tests**, including real PostGIS integration tests.

## Architecture

```text
BPS CSV + GeoJSON ──> import_admin.py ──┐
                                        ├──> PostgreSQL + PostGIS (schema geo)
Geofabrik .osm.pbf ─> osmium + import_osm.py ─┘             │
                                                           v
                                              FastAPI (async psycopg)
                                                           │
                                          ┌────────────────┴────────────────┐
                                          v                                 v
                                Leaflet widget (iframe)          Your app / React
                                postMessage <-> parent
```

Detailed design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). API reference:
[`docs/API.md`](docs/API.md). Widget contract:
[`frontend/README.md`](frontend/README.md).

## Repository layout

```text
backend/            FastAPI app, services, schemas, tests
frontend/
  widget/           standalone Leaflet location picker (single HTML file)
  demo/             static demo API adapter for GitHub Pages (?demo=1)
  pages/            GitHub Pages landing page
  embed/            <peta-location-picker> Web Component
  react/            LocationPicker.tsx
  embed-example.html
migrations/         001 schema, 002 indexes, 003 SQL functions
scripts/            build_pages.py static-site builder
etl/                admin/OSM importers, village linker, demo seed
data/               local BPS/OSM extracts (not committed; see below)
docs/               architecture, API, original dataset README
docker-compose.yml  PostGIS + API (+ optional Photon profile)
```

## Quick start with Docker

Prerequisites: Docker with Compose v2.

```bash
cp .env.example .env
docker compose up -d --build db api
```

Wait until the database is healthy, then apply migrations from the host:

```bash
export DATABASE_URL=postgresql://peta:peta_secret@localhost:5432/peta
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f migrations/001_schema.sql \
  -f migrations/002_indexes.sql \
  -f migrations/003_functions.sql
```

Load the small Bandung demo fixture (Python 3.12 with `psycopg`):

```bash
python -m pip install 'psycopg[binary]'
python etl/seed_demo.py --database-url "$DATABASE_URL"
```

Check the API:

```bash
curl http://localhost:8000/health
curl 'http://localhost:8000/api/v1/geo/reverse?lat=-6.946966&lng=107.598788'
curl 'http://localhost:8000/api/v1/geo/search?q=Cibaduyut'
```

Open Swagger at <http://localhost:8000/docs>. The database is exposed on
`localhost:5432` and the API on `localhost:8000`.

> `make migrate` and `make demo` wrap the same steps. They require `psql` and
> Python dependencies on the host. All commands accept `DATABASE_URL`.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt

# Database only (or use an existing PostGIS instance)
docker compose up -d db
export DATABASE_URL=postgresql://peta:peta_secret@localhost:5432/peta

make migrate
python etl/seed_demo.py --database-url "$DATABASE_URL"

cd backend
uvicorn app.main:app --reload --port 8000
```

Run the test suite:

```bash
cd backend
pytest -q                       # unit + API contract tests, no DB needed
PETA_TEST_DATABASE_URL="$DATABASE_URL" pytest -q   # include PostGIS integration
```

Integration tests expect the demo fixture (`etl/seed_demo.py`). They cover
reverse geocoding, search ranking/geometry, hierarchy, boundaries, ancestors,
cache headers and the SQL functions.

Lint the backend and ETL:

```bash
ruff check backend/app etl
# or
make lint
```

## Importing real data

### Administrative boundaries

Place the BPS dataset under `data/` (the large extracts are not committed to
Git): 34 provinces, 514 cities, 7,228
districts and 83,320 villages, with GeoJSON for levels 1–3.

```bash
python etl/import_admin.py \
  --data-dir data \
  --database-url "$DATABASE_URL"
```

Useful flags:

| Flag | Purpose |
| --- | --- |
| `--province 32` | Import only one province prefix |
| `--skip-villages` | Attributes for levels 1–3 only |
| `--no-geometry` | Fast attribute-only import |
| `--village-centroids file.csv` | Backfill village points (`code,latitude,longitude`) |
| `--batch-size 50` | Rows per upsert batch |
| `--truncate` | Empty `admin_regions` first (destructive) |

Villages have attributes and postal codes but no polygons in the source. After
importing OSM, backfill their centroids:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f etl/link_osm_villages.sql
```

### OpenStreetMap

The workspace includes `indonesia-latest.osm.pbf` (1.7 GB). Install
`osmium-tool` and run:

```bash
bash etl/run_osm_import.sh indonesia-latest.osm.pbf
```

The script filters relevant tags, exports GeoJSONSeq, loads places/roads and
links village centroids. To test with a subset first:

```bash
python etl/import_osm.py \
  --input build/indonesia-filtered.geojsonseq \
  --limit 5000 \
  --database-url "$DATABASE_URL"
```

The importer is idempotent (`ON CONFLICT`), streams input line by line, and
records every run in `geo.import_runs`. For very large volumes, `osm2pgsql`
with a flex style can replace the Python loader; see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Frontend widget

Serve the repository over HTTP (the widget loads Leaflet from a CDN and calls
the API):

```bash
python3 -m http.server 8080
```

Open <http://localhost:8080/frontend/embed-example.html>. It demonstrates the
iframe, theme switching, imperative commands and the `LOCATION_SELECTED`
payload.

Build and preview the static GitHub Pages bundle locally:

```bash
python3 scripts/build_pages.py
python3 -m http.server 8080 -d dist
# open http://localhost:8080/
```

The Pages bundle adds `frontend/demo/demo-api.js` to the widget and is intended
for UI demos; it does not replace the API.

Minimal iframe:

```html
<iframe
  src="/frontend/widget/location-picker.html?apiBase=http://localhost:8000&theme=light"
  title="Pilih lokasi"
  style="width:100%;height:560px;border:0;border-radius:16px"
  allow="geolocation"
  referrerpolicy="strict-origin-when-cross-origin"></iframe>
```

Parent listener:

```js
window.addEventListener('message', (event) => {
  if (event.data?.source !== 'peta-location-picker') return;
  if (event.data.type === 'LOCATION_SELECTED') {
    console.log(event.data.data); // lat, lng, address, region, nearest, ...
  }
});
```

React:

```tsx
<LocationPicker
  apiBase="https://api.example.id"
  targetOrigin={window.location.origin}
  allowedOrigin={window.location.origin}
  onSelectLocation={(payload) => console.log(payload.formatted_address)}
/>
```

See [`frontend/README.md`](frontend/README.md) for the full message contract,
Web Component usage and production security notes.

## Configuration

Copy `.env.example` to `.env` and adjust:

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://peta:peta_secret@localhost:5432/peta` | PostGIS connection |
| `DB_POOL_MIN` / `DB_POOL_MAX` | 2 / 10 | Async pool bounds |
| `STATEMENT_TIMEOUT_MS` | 5000 | Per-query timeout |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `API_KEYS` | empty | Comma-separated keys; empty disables auth |
| `RATE_LIMIT_PER_MINUTE` | 120 | Per-client limit |
| `CACHE_TTL_SECONDS` | 86400 | Database cache TTL; `0` disables |
| `NOMINATIM_URL` | empty | Optional reverse enrichment |
| `PHOTON_URL` | empty | Optional forward-search enrichment |
| `TILE_URL` / `TILE_ATTRIBUTION` | OSM standard | Basemap for the widget |

The widget also accepts overrides through query parameters or
`PETA_CONFIGURE`.

## Production notes

- Set `CORS_ORIGINS` to the exact parent/widget origins.
- Set `API_KEYS` and terminate TLS at a reverse proxy; never ship a secret key
  in a public HTML page.
- Keep `targetOrigin`/`allowedOrigin` specific; `*` is for local demos only.
- Replace the public OSM tile server for high traffic and follow its usage
  policy.
- Run `VACUUM (ANALYZE)` after large imports; the ETL already runs `ANALYZE`.
- Monitor `geo.import_runs`, `/health` and query latency. The API emits
  `X-Request-ID` and `X-Response-Time` on every response.

## Known limitations

- Village polygons are absent from the bundled BPS GeoJSON. Village-level
  reverse results use centroids and are flagged `approximate`; supply polygons
  or centroids if exact village containment is required.
- The full PBF/GeoJSON import is intentionally left to the operator. A real
  single-province import (province 32: 6,618 regions from 654 GeoJSON files)
  and a sample OSM import were validated; size the full run on your hardware.
- Nominatim/Photon are optional. Without them, results are limited to the
  imported admin boundaries, POIs and roads.
- OSM names and addresses vary in quality; `nearest` is best-effort and includes
  distance metadata.

## Data source and license

Boundary and postal data originate from Badan Pusat Statistik (BPS), packaged
by the original dataset project. OSM data © OpenStreetMap contributors, ODbL.
The original dataset README and attribution are preserved in
[`docs/DATA-SOURCE.md`](docs/DATA-SOURCE.md). This project is released under
the MIT license; see [`LICENSE`](LICENSE).

