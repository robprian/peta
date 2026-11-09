#!/usr/bin/env bash
# ============================================================================
#  ETL OpenStreetMap Indonesia (Geofabrik .osm.pbf)
#
#  Prasyarat: osmium-tool, python3 + psycopg, PostGIS sudah dimigrasikan.
#  Pemakaian:
#     ./etl/run_osm_import.sh [indonesia-latest.osm.pbf]
#
#  Output:
#     build/indonesia-filtered.osm.pbf
#     build/indonesia-filtered.geojsonseq
# ============================================================================
set -euo pipefail

PBF="${1:-${OSM_PBF:-indonesia-latest.osm.pbf}}"
WORKDIR="${WORKDIR:-build}"
FILTERED="$WORKDIR/indonesia-filtered.osm.pbf"
GEOJSON="$WORKDIR/indonesia-filtered.geojsonseq"
DATABASE_URL="${DATABASE_URL:-postgresql://peta:peta_secret@localhost:5432/peta}"

if ! command -v osmium >/dev/null 2>&1; then
  echo "ERROR: osmium tidak ditemukan. Install: apt-get install osmium-tool" >&2
  exit 1
fi
if [ ! -f "$PBF" ]; then
  echo "ERROR: file PBF tidak ditemukan: $PBF" >&2
  exit 1
fi

mkdir -p "$WORKDIR"

echo "==> [1/4] Filter fitur OSM yang dibutuhkan"
osmium tags-filter "$PBF" \
  nwr/place=city,town,village,hamlet,suburb,neighbourhood,quarter,locality,isolated_dwelling \
  nwr/amenity \
  nwr/shop \
  nwr/tourism \
  nwr/office \
  nwr/healthcare \
  nwr/leisure \
  nwr/historic \
  nwr/addr:housenumber \
  nwr/addr:street \
  w/highway \
  -o "$FILTERED" --overwrite

echo "==> [2/4] Export ke GeoJSONSeq"
osmium export "$FILTERED" \
  --add-unique-id=type_id \
  --geometry-types=point,linestring,polygon \
  -f geojsonseq \
  -o "$GEOJSON" --overwrite

echo "==> [3/4] Import ke PostGIS"
python3 etl/import_osm.py --input "$GEOJSON" --database-url "$DATABASE_URL"

echo "==> [4/4] Isi centroid desa dari place node OSM"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f etl/link_osm_villages.sql

echo "Selesai. Cek: SELECT count(*) FROM geo.osm_places;"
