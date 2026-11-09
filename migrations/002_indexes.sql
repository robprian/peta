-- ============================================================================
--  Peta Indonesia — 002_indexes.sql
--  Indeks spasial & pencarian. Jalankan setelah 001_schema.sql.
--  Catatan: saat import massal, lebih cepat DROP indeks GIN/GiST lalu
--  CREATE ulang setelah COPY selesai (lihat etl/run_import.sh).
-- ============================================================================
BEGIN;
SET LOCAL search_path = geo, public;

-- ---------------------------------------------------------------------------
-- admin_regions
-- ---------------------------------------------------------------------------
-- Inti reverse geocode: ST_Covers / ST_Contains / ST_Intersects.
CREATE INDEX IF NOT EXISTS admin_regions_geom_gix
    ON geo.admin_regions USING GIST (geom)
    WHERE geom IS NOT NULL;

CREATE INDEX IF NOT EXISTS admin_regions_geom_simplified_gix
    ON geo.admin_regions USING GIST (geom_simplified)
    WHERE geom_simplified IS NOT NULL;

-- Nearest fallback (desa tanpa polygon / titik di luar batas).
CREATE INDEX IF NOT EXISTS admin_regions_centroid_gix
    ON geo.admin_regions USING GIST (centroid)
    WHERE centroid IS NOT NULL;

-- Traversal hierarki.
CREATE INDEX IF NOT EXISTS admin_regions_level_idx       ON geo.admin_regions (level);
CREATE INDEX IF NOT EXISTS admin_regions_parent_idx      ON geo.admin_regions (parent_code);
CREATE INDEX IF NOT EXISTS admin_regions_province_idx    ON geo.admin_regions (province_code);
CREATE INDEX IF NOT EXISTS admin_regions_regency_idx     ON geo.admin_regions (regency_code);
CREATE INDEX IF NOT EXISTS admin_regions_district_idx    ON geo.admin_regions (district_code);
CREATE INDEX IF NOT EXISTS admin_regions_level_parent_idx
    ON geo.admin_regions (level, parent_code);

-- Autocomplete nama wilayah (prefix & fuzzy).
CREATE INDEX IF NOT EXISTS admin_regions_name_trgm_gix
    ON geo.admin_regions USING GIN (lower(name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS admin_regions_fullname_trgm_gix
    ON geo.admin_regions USING GIN (lower(full_name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS admin_regions_search_tsv_gix
    ON geo.admin_regions USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS admin_regions_postal_gix
    ON geo.admin_regions USING GIN (postal_codes);

-- ---------------------------------------------------------------------------
-- osm_places
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS osm_places_geom_gix
    ON geo.osm_places USING GIST (geom);

-- ST_DWithin / KNN berbasis meter.
CREATE INDEX IF NOT EXISTS osm_places_geog_gix
    ON geo.osm_places USING GIST ((geom::geography));

CREATE INDEX IF NOT EXISTS osm_places_name_trgm_gix
    ON geo.osm_places USING GIN (lower(name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS osm_places_display_trgm_gix
    ON geo.osm_places USING GIN (lower(display_name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS osm_places_search_tsv_gix
    ON geo.osm_places USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS osm_places_category_idx
    ON geo.osm_places (category, type);
CREATE INDEX IF NOT EXISTS osm_places_postcode_idx
    ON geo.osm_places (addr_postcode);

-- ---------------------------------------------------------------------------
-- osm_roads
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS osm_roads_geom_gix
    ON geo.osm_roads USING GIST (geom);
CREATE INDEX IF NOT EXISTS osm_roads_geog_gix
    ON geo.osm_roads USING GIST ((geom::geography));
CREATE INDEX IF NOT EXISTS osm_roads_name_trgm_gix
    ON geo.osm_roads USING GIN (lower(name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS osm_roads_highway_idx
    ON geo.osm_roads (highway);

-- ---------------------------------------------------------------------------
-- cache
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS geocode_cache_expires_idx
    ON geo.geocode_cache (expires_at);

ANALYZE geo.admin_regions;
ANALYZE geo.osm_places;
ANALYZE geo.osm_roads;

COMMIT;
