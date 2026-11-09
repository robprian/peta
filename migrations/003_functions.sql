-- ============================================================================
--  Peta Indonesia — 003_functions.sql
--  Helper hierarki + inti reverse geocoding di sisi database.
-- ============================================================================
BEGIN;
SET LOCAL search_path = geo, public;

-- ---------------------------------------------------------------------------
-- Isi ulang admin_regions.full_name, mis. "Cibaduyut, Bojongloa Kidul, ..."
-- Dipanggil di akhir ETL (bukan trigger, agar import massal tetap cepat).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION geo.refresh_region_full_names()
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_rows bigint;
BEGIN
    WITH RECURSIVE tree AS (
        SELECT r.code, r.level, r.name::text AS full_name
        FROM geo.admin_regions r
        WHERE r.level = 1
        UNION ALL
        SELECT c.code, c.level, c.name || ', ' || t.full_name
        FROM geo.admin_regions c
        JOIN tree t ON c.parent_code = t.code
        WHERE c.level = t.level + 1
    )
    UPDATE geo.admin_regions a
       SET full_name = t.full_name
      FROM tree t
     WHERE a.code = t.code
       AND a.full_name IS DISTINCT FROM t.full_name;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION geo.refresh_region_full_names() IS
    'Bangun ulang full_name seluruh wilayah secara rekursif. Panggil setelah ETL.';

-- ---------------------------------------------------------------------------
-- Cari rantai wilayah untuk satu titik.
--   1) ST_Covers pada polygon terdalam (desa -> kec -> kab -> prov)
--   2) Bila polygon level bawah tidak tersedia, pakai centroid terdekat
--      di dalam wilayah induk (data BPS lama tidak punya polygon desa).
--   3) Bila titik di luar semua polygon, fallback polygon terdekat <= 25 km.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION geo.locate_admin(
    p_lng double precision,
    p_lat double precision
)
RETURNS TABLE (
    province_code  varchar(13),
    province_name  text,
    regency_code   varchar(13),
    regency_name   text,
    district_code  varchar(13),
    district_name  text,
    village_code   varchar(13),
    village_name   text,
    postal_codes   text[],
    match_level    smallint,
    is_approximate boolean,
    distance_m     double precision
)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_pt       geometry := ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326);
    v_hit      geo.admin_regions%ROWTYPE;
    v_cur      geo.admin_regions%ROWTYPE;
    v_prov     geo.admin_regions%ROWTYPE;
    v_reg      geo.admin_regions%ROWTYPE;
    v_dist     geo.admin_regions%ROWTYPE;
    v_vil      geo.admin_regions%ROWTYPE;
    v_match    smallint := 0;
    v_approx   boolean := false;
    v_dist_m   double precision := 0;
BEGIN
    -- Bounding box Indonesia (termasuk laut teritorial dekat).
    IF p_lng IS NULL OR p_lat IS NULL
       OR p_lng < 94 OR p_lng > 142
       OR p_lat < -12 OR p_lat > 7 THEN
        RETURN;
    END IF;

    -- 1. Polygon terdalam yang memuat titik.
    SELECT * INTO v_hit
    FROM geo.admin_regions r
    WHERE r.geom IS NOT NULL
      AND ST_Covers(r.geom, v_pt)
    ORDER BY r.level DESC, ST_Area(r.geom) ASC
    LIMIT 1;

    IF v_hit.code IS NOT NULL THEN
        v_match := v_hit.level;
        v_cur := v_hit;
    ELSE
        -- 3. Di luar batas: gunakan polygon terdekat (maks. 25 km).
        SELECT * INTO v_hit
        FROM geo.admin_regions r
        WHERE r.geom IS NOT NULL
          AND ST_DWithin(r.geom::geography, v_pt::geography, 25000)
        ORDER BY r.geom::geography <-> v_pt::geography, r.level DESC
        LIMIT 1;

        IF v_hit.code IS NULL THEN
            RETURN;
        END IF;

        v_match  := v_hit.level;
        v_dist_m := ST_Distance(v_hit.geom::geography, v_pt::geography);
        v_approx := true;
        v_cur    := v_hit;
    END IF;

    -- 2a. Naik ke seluruh leluhur via parent_code.
    WHILE v_cur.code IS NOT NULL LOOP
        CASE v_cur.level
            WHEN 1 THEN IF v_prov.code IS NULL THEN v_prov := v_cur; END IF;
            WHEN 2 THEN IF v_reg.code  IS NULL THEN v_reg  := v_cur; END IF;
            WHEN 3 THEN IF v_dist.code IS NULL THEN v_dist := v_cur; END IF;
            WHEN 4 THEN IF v_vil.code  IS NULL THEN v_vil  := v_cur; END IF;
        END CASE;
        EXIT WHEN v_cur.level = 1;
        SELECT * INTO v_cur FROM geo.admin_regions r WHERE r.code = v_cur.parent_code;
    END LOOP;

    -- 2b. Lengkapi level yang tidak punya polygon (centroid terdekat).
    IF v_reg.code IS NULL AND v_prov.code IS NOT NULL THEN
        SELECT * INTO v_reg
        FROM geo.admin_regions r
        WHERE r.level = 2 AND r.province_code = v_prov.code
          AND r.centroid IS NOT NULL
        ORDER BY r.centroid <-> v_pt
        LIMIT 1;
        IF v_reg.code IS NOT NULL THEN
            v_approx := true;
        END IF;
    END IF;

    IF v_dist.code IS NULL AND v_reg.code IS NOT NULL THEN
        SELECT * INTO v_dist
        FROM geo.admin_regions r
        WHERE r.level = 3 AND r.regency_code = v_reg.code
          AND r.centroid IS NOT NULL
        ORDER BY r.centroid <-> v_pt
        LIMIT 1;
        IF v_dist.code IS NOT NULL THEN
            v_approx := true;
        END IF;
    END IF;

    IF v_vil.code IS NULL AND v_dist.code IS NOT NULL THEN
        SELECT * INTO v_vil
        FROM geo.admin_regions r
        WHERE r.level = 4 AND r.parent_code = v_dist.code
          AND r.centroid IS NOT NULL
        ORDER BY r.centroid <-> v_pt
        LIMIT 1;
        IF v_vil.code IS NOT NULL THEN
            v_approx := true;
        END IF;
    END IF;

    IF v_vil.code IS NULL AND v_reg.code IS NOT NULL THEN
        SELECT * INTO v_vil
        FROM geo.admin_regions r
        WHERE r.level = 4 AND r.regency_code = v_reg.code
          AND r.centroid IS NOT NULL
          AND ST_DWithin(r.centroid::geography, v_pt::geography, 25000)
        ORDER BY r.centroid <-> v_pt
        LIMIT 1;
        IF v_vil.code IS NOT NULL THEN
            v_approx := true;
        END IF;
    END IF;

    RETURN QUERY SELECT
        v_prov.code, v_prov.name,
        v_reg.code,  v_reg.name,
        v_dist.code, v_dist.name,
        v_vil.code,  v_vil.name,
        CASE
            WHEN cardinality(v_vil.postal_codes)  > 0 THEN v_vil.postal_codes
            WHEN cardinality(v_dist.postal_codes) > 0 THEN v_dist.postal_codes
            WHEN cardinality(v_reg.postal_codes)  > 0 THEN v_reg.postal_codes
            ELSE v_prov.postal_codes
        END,
        v_match, v_approx, v_dist_m;
END;
$$;

COMMENT ON FUNCTION geo.locate_admin(double precision, double precision) IS
    'Reverse lookup hierarki wilayah; aman untuk desa tanpa polygon.';

-- ---------------------------------------------------------------------------
-- Reverse geocode lengkap: hierarki + jalan/POI terdekat + alamat terformat.
-- Satu round-trip untuk endpoint /api/v1/geo/reverse.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION geo.reverse_geocode(
    p_lat double precision,
    p_lng double precision
)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_pt       geometry := ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326);
    v_admin    record;
    v_road     record;
    v_poi      record;
    v_street   text;
    v_postcode text;
    v_line1    text;
    v_label    text;
    v_formatted text;
BEGIN
    IF p_lat IS NULL OR p_lng IS NULL THEN
        RETURN jsonb_build_object('found', false, 'reason', 'invalid_coordinates');
    END IF;

    SELECT * INTO v_admin FROM geo.locate_admin(p_lng, p_lat);

    IF NOT FOUND OR v_admin.province_code IS NULL THEN
        RETURN jsonb_build_object(
            'found',    false,
            'reason',   'outside_indonesia',
            'location', jsonb_build_object('lat', p_lat, 'lng', p_lng)
        );
    END IF;

    -- Jalan bernama terdekat (<= 250 m).
    SELECT r.name, r.ref, r.highway,
           ST_Distance(r.geom::geography, v_pt::geography) AS distance_m
      INTO v_road
      FROM geo.osm_roads r
     WHERE r.geom && ST_Expand(v_pt, 0.01)
       AND ST_DWithin(r.geom::geography, v_pt::geography, 250)
       AND r.name IS NOT NULL
     ORDER BY r.geom::geography <-> v_pt::geography
     LIMIT 1;

    -- POI/permukiman terdekat (<= 300 m).
    SELECT p.name, p.display_name, p.category, p.type,
           p.addr_housenumber, p.addr_street, p.addr_postcode,
           p.lat, p.lon,
           ST_Distance(p.geom::geography, v_pt::geography) AS distance_m
      INTO v_poi
      FROM geo.osm_places p
     WHERE p.geom && ST_Expand(v_pt, 0.01)
       AND ST_DWithin(p.geom::geography, v_pt::geography, 300)
       AND p.name IS NOT NULL
     ORDER BY p.geom::geography <-> v_pt::geography
     LIMIT 1;

    v_street   := COALESCE(NULLIF(v_poi.addr_street, ''), NULLIF(v_road.name, ''));
    v_postcode := COALESCE(NULLIF(v_poi.addr_postcode, ''), v_admin.postal_codes[1]);
    v_line1    := NULLIF(concat_ws(' ', v_street, v_poi.addr_housenumber), '');
    v_formatted := concat_ws(', ',
        v_line1,
        v_admin.village_name,
        v_admin.district_name,
        v_admin.regency_name,
        v_admin.province_name,
        v_postcode
    );
    v_label := COALESCE(NULLIF(v_poi.display_name, ''), v_formatted);

    RETURN jsonb_build_object(
        'found', true,
        'location', jsonb_build_object('lat', p_lat, 'lng', p_lng),
        'region', jsonb_build_object(
            'province', CASE WHEN v_admin.province_code IS NULL THEN NULL ELSE
                jsonb_build_object('code', v_admin.province_code, 'name', v_admin.province_name) END,
            'regency', CASE WHEN v_admin.regency_code IS NULL THEN NULL ELSE
                jsonb_build_object('code', v_admin.regency_code, 'name', v_admin.regency_name) END,
            'district', CASE WHEN v_admin.district_code IS NULL THEN NULL ELSE
                jsonb_build_object('code', v_admin.district_code, 'name', v_admin.district_name) END,
            'village', CASE WHEN v_admin.village_code IS NULL THEN NULL ELSE
                jsonb_build_object('code', v_admin.village_code, 'name', v_admin.village_name) END
        ),
        'address', jsonb_build_object(
            'line1',       v_line1,
            'street',      v_street,
            'housenumber', v_poi.addr_housenumber,
            'village',     v_admin.village_name,
            'district',    v_admin.district_name,
            'regency',     v_admin.regency_name,
            'province',    v_admin.province_name,
            'postcode',    v_postcode,
            'formatted',   v_formatted,
            'label',       v_label
        ),
        'nearest', jsonb_build_object(
            'road', CASE WHEN v_road.name IS NULL THEN NULL ELSE jsonb_build_object(
                'name', v_road.name, 'ref', v_road.ref, 'highway', v_road.highway,
                'distance_m', round(v_road.distance_m::numeric, 1)) END,
            'place', CASE WHEN v_poi.name IS NULL THEN NULL ELSE jsonb_build_object(
                'name', v_poi.name, 'category', v_poi.category, 'type', v_poi.type,
                'lat', v_poi.lat, 'lon', v_poi.lon,
                'distance_m', round(v_poi.distance_m::numeric, 1)) END
        ),
        'match', jsonb_build_object(
            'method', CASE
                WHEN NOT v_admin.is_approximate AND v_admin.match_level > 0 THEN 'polygon'
                WHEN v_admin.match_level > 0 THEN 'nearest'
                ELSE 'none' END,
            'level',       v_admin.match_level,
            'approximate', v_admin.is_approximate,
            'distance_m',  round(v_admin.distance_m::numeric, 1),
            'confidence',  CASE
                WHEN v_admin.village_code IS NOT NULL AND NOT v_admin.is_approximate THEN 0.98
                WHEN v_admin.village_code IS NOT NULL THEN 0.80
                WHEN v_admin.district_code IS NOT NULL THEN 0.65
                WHEN v_admin.regency_code IS NOT NULL THEN 0.50
                ELSE 0.30 END
        ),
        'source', 'postgis+osm'
    );
END;
$$;

COMMENT ON FUNCTION geo.reverse_geocode(double precision, double precision) IS
    'Reverse geocode Indonesia: hierarki administratif + jalan/POI + alamat.';

COMMIT;

