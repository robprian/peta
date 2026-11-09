-- ============================================================================
--  Peta Indonesia — 001_schema.sql
--  PostgreSQL 15+ / PostGIS 3.4+
--
--  Run:  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_schema.sql
-- ============================================================================
BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS geo;
SET LOCAL search_path = geo, public;

-- ---------------------------------------------------------------------------
-- 1. Hierarki wilayah administrasi (BPS / Kemendagri)
--    Satu tabel untuk 4 level. Kode BPS 10 digit:
--      2 = provinsi, 4 = kab/kota, 7 = kecamatan, 10 = desa/kelurahan
--    Kolom province/regency/district_code didenormalisasi agar reverse
--    geocode cukup satu lookup + join, tanpa recursive CTE.
-- ---------------------------------------------------------------------------
CREATE TABLE geo.admin_regions (
    code              varchar(13) PRIMARY KEY,
    kemendagri_code   varchar(13),
    level             smallint NOT NULL CHECK (level BETWEEN 1 AND 4),
    name              text NOT NULL,
    full_name         text,                       -- "Cibaduyut, Bojongloa Kidul, Bandung, Jawa Barat"
    parent_code       varchar(13) REFERENCES geo.admin_regions(code)
                          DEFERRABLE INITIALLY DEFERRED,
    province_code     varchar(13),
    regency_code      varchar(13),
    district_code     varchar(13),
    postal_codes      text[] NOT NULL DEFAULT '{}',
    geom              geometry(MultiPolygon, 4326),
    geom_simplified   geometry(MultiPolygon, 4326),  -- untuk render batas di peta
    centroid          geometry(Point, 4326),
    bbox              geometry(Polygon, 4326),
    area_km2          double precision,
    population        integer,
    source            text NOT NULL DEFAULT 'BPS',
    attrs             jsonb NOT NULL DEFAULT '{}'::jsonb,
    search_vector     tsvector GENERATED ALWAYS AS (
                          to_tsvector('simple',
                              coalesce(name, '') || ' ' || coalesce(full_name, ''))
                      ) STORED,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT admin_regions_level_code_chk CHECK (
        (level = 1 AND length(code) = 2) OR
        (level = 2 AND length(code) = 4) OR
        (level = 3 AND length(code) = 7) OR
        (level = 4 AND length(code) = 10)
    )
);

COMMENT ON TABLE  geo.admin_regions IS
    'Batas & atribut wilayah administratif Indonesia (provinsi s.d. desa/kelurahan).';
COMMENT ON COLUMN geo.admin_regions.code IS
    'Kode BPS/Kemendagri tanpa prefix negara. 2/4/7/10 digit.';
COMMENT ON COLUMN geo.admin_regions.geom_simplified IS
    'ST_SimplifyPreserveTopology(geom, 0.0005) — untuk payload peta, bukan analisis.';

-- ---------------------------------------------------------------------------
-- 2. OSM: tempat / POI / alamat (node, way, relation hasil osm2pgsql)
-- ---------------------------------------------------------------------------
CREATE TABLE geo.osm_places (
    id                bigserial PRIMARY KEY,
    osm_type          char(1) NOT NULL CHECK (osm_type IN ('n', 'w', 'r')),
    osm_id            bigint NOT NULL,
    name              text,
    display_name      text,
    category          text,          -- place, amenity, shop, highway, tourism, ...
    type              text,          -- city, village, restaurant, ...
    lat               double precision NOT NULL,
    lon               double precision NOT NULL,
    geom              geometry(Point, 4326) NOT NULL,
    addr_housenumber  text,
    addr_street       text,
    addr_postcode     text,
    addr_village      text,
    addr_subdistrict  text,
    addr_city         text,
    addr_district     text,
    addr_state        text,
    tags              jsonb NOT NULL DEFAULT '{}'::jsonb,
    importance        real NOT NULL DEFAULT 0,
    rank_search       smallint NOT NULL DEFAULT 30,
    search_vector     tsvector GENERATED ALWAYS AS (
                          to_tsvector('simple',
                              coalesce(name, '') || ' ' || coalesce(display_name, ''))
                      ) STORED,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (osm_type, osm_id)
);

COMMENT ON TABLE geo.osm_places IS
    'POI, permukiman, dan alamat dari ekstrak Geofabrik. category/type mengikuti tag OSM.';

-- ---------------------------------------------------------------------------
-- 3. OSM: jaringan jalan (untuk "jalan terdekat" + geocoding alamat)
-- ---------------------------------------------------------------------------
CREATE TABLE geo.osm_roads (
    id          bigserial PRIMARY KEY,
    osm_id      bigint NOT NULL,
    name        text,
    highway     text,                 -- residential, primary, service, ...
    ref         text,                 -- nomor jalan nasional/provinsi
    geom        geometry(Geometry, 4326) NOT NULL,  -- LineString / MultiLineString
    tags        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (osm_id)
);

COMMENT ON TABLE geo.osm_roads IS
    'Jalan dari OSM; name/ref dipakai untuk melengkapi alamat hasil reverse geocode.';

-- ---------------------------------------------------------------------------
-- 4. Kode pos (tabel referensi + pemetaan wilayah)
-- ---------------------------------------------------------------------------
CREATE TABLE geo.postal_codes (
    code           varchar(5) PRIMARY KEY,
    name           text,
    province_codes text[] NOT NULL DEFAULT '{}',
    attrs          jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 5. Cache hasil geocode (reverse/forward) — TTL, aman untuk multi-instance
-- ---------------------------------------------------------------------------
CREATE TABLE geo.geocode_cache (
    cache_key   text PRIMARY KEY,
    payload     jsonb NOT NULL,
    expires_at  timestamptz NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 6. Audit ETL
-- ---------------------------------------------------------------------------
CREATE TABLE geo.import_runs (
    id          bigserial PRIMARY KEY,
    dataset     text NOT NULL,          -- admin_regions | osm_places | osm_roads
    source_file text,
    status      text NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'success', 'failed')),
    rows_loaded bigint NOT NULL DEFAULT 0,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    notes       text
);

-- ---------------------------------------------------------------------------
-- 7. Trigger updated_at
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION geo.touch_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_admin_regions_touch
    BEFORE UPDATE ON geo.admin_regions
    FOR EACH ROW EXECUTE FUNCTION geo.touch_updated_at();

CREATE TRIGGER trg_osm_places_touch
    BEFORE UPDATE ON geo.osm_places
    FOR EACH ROW EXECUTE FUNCTION geo.touch_updated_at();

COMMIT;
