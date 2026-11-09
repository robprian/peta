-- ============================================================================
--  link_osm_villages.sql
--  Dataset BPS tidak menyertakan polygon desa. Setelah OSM diimpor, isi
--  centroid desa/kelurahan dari node place=village/hamlet/suburb yang namanya
--  sama dan berada di dalam polygon kecamatan.
--
--  Jalankan setelah import_admin.py dan import_osm.py:
--     psql "$DATABASE_URL" -f etl/link_osm_villages.sql
-- ============================================================================
BEGIN;
SET LOCAL search_path = geo, public;

WITH candidates AS (
    SELECT
        v.code,
        p.geom,
        ROW_NUMBER() OVER (
            PARTITION BY v.code
            ORDER BY p.importance DESC,
                     ST_Distance(p.geom::geography, d.centroid::geography)
        ) AS rn
    FROM geo.admin_regions v
    JOIN geo.admin_regions d
      ON d.code = v.parent_code AND d.level = 3
    JOIN geo.osm_places p
      ON lower(p.name) = lower(v.name)
     AND p.type IN ('village', 'hamlet', 'suburb', 'neighbourhood', 'quarter')
    WHERE v.level = 4
      AND v.centroid IS NULL
      AND d.geom IS NOT NULL
      AND ST_Contains(d.geom, p.geom)
)
UPDATE geo.admin_regions v
   SET centroid = c.geom,
       updated_at = now()
  FROM candidates c
 WHERE v.code = c.code
   AND c.rn = 1;

COMMIT;
