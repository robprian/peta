/*
 * Demo API statis untuk GitHub Pages.
 *
 * Aktif dengan ?demo=1, atau otomatis di *.github.io selama tidak ada apiBase
 * (GitHub Pages tidak bisa menjalankan FastAPI/PostGIS). Data dimuat dari
 * demo-data.js: batas BPS untuk provinsi/kota/kecamatan dan batas
 * desa/kelurahan dari OpenStreetMap. Ini demo UI, bukan pengganti backend.
 */
(() => {
  const params = new URLSearchParams(location.search);
  const demoParam = params.get('demo');
  if (demoParam === '0') return;
  const onPages = /\.github\.io$/i.test(location.hostname);
  const hasApi = Boolean(params.get('apiBase'));
  if (!(demoParam === '1' || (onPages && !hasApi))) return;

  const scriptUrl = document.currentScript?.src || location.href;

  function boot(DATA) {
    if (!DATA || !Array.isArray(DATA.regions)) return;
    const REGIONS = DATA.regions;
    const PLACES = DATA.places || [];
    const ROADS = DATA.roads || [];
    const BY = new Map(REGIONS.map((r) => [r.code, r]));
    const LVL = ['', 'province', 'regency', 'district', 'village'];
    const json = (data, status = 200) => new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
    const rad = (d) => (d * Math.PI) / 180;
    const hav = (a, b, c, d) => {
      const dLat = rad(c - a);
      const dLng = rad(d - b);
      const h = Math.sin(dLat / 2) ** 2
        + Math.cos(rad(a)) * Math.cos(rad(c)) * Math.sin(dLng / 2) ** 2;
      return 6371008.8 * 2 * Math.asin(Math.sqrt(h));
    };

    function ringContains(lng, lat, ring) {
      let inside = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
        const [xi, yi] = ring[i];
        const [xj, yj] = ring[j];
        if ((yi > lat) !== (yj > lat)
            && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
          inside = !inside;
        }
      }
      return inside;
    }

    function geomContains(lng, lat, geom) {
      if (!geom) return false;
      if (geom.type === 'Polygon') {
        const [outer, ...holes] = geom.coordinates;
        return ringContains(lng, lat, outer)
          && !holes.some((hole) => ringContains(lng, lat, hole));
      }
      if (geom.type === 'MultiPolygon') {
        return geom.coordinates.some((polygon) => geomContains(lng, lat, {
          type: 'Polygon', coordinates: polygon,
        }));
      }
      return false;
    }

    const chainOf = (region) => {
      const out = { province: null, regency: null, district: null, village: null };
      let cur = region;
      while (cur) {
        const key = LVL[cur.level];
        if (key && !out[key]) out[key] = { code: cur.code, name: cur.name };
        cur = BY.get(cur.parent);
      }
      return out;
    };
    const labelOf = (region) => {
      const ch = chainOf(region);
      return [ch.village, ch.district, ch.regency, ch.province]
        .filter(Boolean).map((x) => x.name).join(', ');
    };
    const fullNameOf = (region) => labelOf(region);
    const centroidOf = (region) => region.centroid || [0, 0];

    function segDist(lat, lng, a, b) {
      const k = Math.cos(rad(lat));
      const px = (lng - a[1]) * k;
      const py = lat - a[0];
      const dx = (b[1] - a[1]) * k;
      const dy = b[0] - a[0];
      const len = dx * dx + dy * dy;
      const t = len ? Math.max(0, Math.min(1, (px * dx + py * dy) / len)) : 0;
      return Math.hypot(px - t * dx, py - t * dy) * 111320;
    }

    function nearestRoad(lat, lng) {
      let road = null;
      let best = Infinity;
      for (const r of ROADS) {
        for (let i = 1; i < r.pts.length; i += 1) {
          const d = segDist(lat, lng, r.pts[i - 1], r.pts[i]);
          if (d < best) { best = d; road = r; }
        }
      }
      return best <= 250
        ? { name: road.name, ref: road.ref || null, highway: road.highway,
            distance_m: Math.round(best * 10) / 10 }
        : null;
    }

    function nearestPlace(lat, lng) {
      let place = null;
      let best = Infinity;
      for (const p of PLACES) {
        const d = hav(lat, lng, p.lat, p.lon);
        if (d < best) { best = d; place = p; }
      }
      if (!place || best > 300) return { place: null, row: null };
      return {
        place: { name: place.name, category: place.category, type: place.type,
          lat: place.lat, lon: place.lon, distance_m: Math.round(best * 10) / 10 },
        row: place,
      };
    }

    function deepestAt(lat, lng) {
      let hit = null;
      for (const r of REGIONS) {
        if (!geomContains(lng, lat, r.geometry)) continue;
        if (!hit || r.level > hit.level
            || (r.level === hit.level && (r.area || 0) < (hit.area || 0))) {
          hit = r;
        }
      }
      return hit;
    }

    function closestRegion(lat, lng, filter) {
      let best = null;
      let bestDist = Infinity;
      for (const r of REGIONS) {
        if (filter && !filter(r)) continue;
        const [rLat, rLng] = centroidOf(r);
        const d = hav(lat, lng, rLat, rLng);
        if (d < bestDist) { bestDist = d; best = r; }
      }
      return { region: best, distance: bestDist };
    }

    function reverse(lat, lng) {
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        throw new Error('Koordinat tidak valid');
      }
      let hit = deepestAt(lat, lng);
      let approximate = false;
      let distance = 0;
      if (!hit) {
        const found = closestRegion(lat, lng);
        if (!found.region || found.distance > 25000) {
          return { found: false, reason: 'no_result', location: { lat, lng } };
        }
        hit = found.region;
        approximate = true;
        distance = found.distance;
      }

      const ch = chainOf(hit);
      const fill = (level, parentCode) => {
        const key = LVL[level];
        if (ch[key] || !parentCode) return;
        const prefix = { 2: 2, 3: 4, 4: 7 }[level];
        const found = closestRegion(lat, lng, (r) => (
          r.level === level && r.parent === parentCode && r.code.slice(0, prefix) === parentCode
        ));
        if (found.region) {
          ch[key] = { code: found.region.code, name: found.region.name };
          approximate = true;
          if (level === 4) distance = found.distance;
        }
      };
      if (ch.province) fill(2, ch.province.code);
      if (ch.regency) fill(3, ch.regency.code);
      if (ch.district) fill(4, ch.district.code);

      const road = nearestRoad(lat, lng);
      const nearest = nearestPlace(lat, lng);
      const deepest = ch.village || ch.district || ch.regency || ch.province;
      const regionPostal = deepest ? (BY.get(deepest.code)?.postal || []) : [];
      const postcode = nearest.row?.postcode || regionPostal[0] || null;
      const parts = [ch.village, ch.district, ch.regency, ch.province]
        .filter(Boolean).map((x) => x.name);
      const label = parts.join(', ');
      const line1 = road?.name || nearest.place?.name || null;
      const formatted = [line1, ...parts, postcode].filter(Boolean).join(', ');
      const level = ch.village ? 4 : ch.district ? 3 : ch.regency ? 2 : 1;
      const confidence = level === 4
        ? (approximate ? 0.8 : 0.98)
        : level === 3 ? 0.65 : level === 2 ? 0.5 : 0.3;

      return {
        found: true,
        location: { lat, lng },
        region: ch,
        address: {
          line1,
          street: road?.name || null,
          housenumber: null,
          village: ch.village?.name || null,
          district: ch.district?.name || null,
          regency: ch.regency?.name || null,
          province: ch.province?.name || null,
          postcode,
          formatted,
          label,
        },
        nearest: { road, place: nearest.place },
        match: {
          method: approximate ? 'nearest' : 'polygon',
          level: hit.level,
          approximate,
          distance_m: Math.round(distance * 10) / 10,
          confidence,
        },
        source: 'demo+static',
      };
    }

    function search(text, limit, type, withGeometry) {
      const q = String(text || '').trim().toLowerCase();
      if (!q) return { query: text, count: 0, results: [], took_ms: 0 };
      const out = [];
      if (type !== 'place') {
        for (const r of REGIONS) {
          const name = r.name.toLowerCase();
          const full = fullNameOf(r).toLowerCase();
          let rank = 0;
          if (name === q) rank = 4;
          else if (name.startsWith(q)) rank = 3;
          else if (full.includes(q)) rank = 2;
          else if (r.code.startsWith(q)) rank = 1;
          if (!rank) continue;
          const [lat, lng] = centroidOf(r);
          out.push({
            _rank: rank,
            id: r.code, kind: 'region', name: r.name, label: fullNameOf(r),
            level: r.level, lat, lng, bbox: r.bbox || null,
            postcode: (r.postal || [])[0] || null,
            category: null, type: null, region: chainOf(r),
            score: rank === 4 ? 1 : rank === 3 ? 0.9 : rank === 2 ? 0.7 : 0.55,
            geometry: withGeometry ? r.geometry : null,
          });
        }
      }
      if (type !== 'region') {
        for (const p of PLACES) {
          const name = p.name.toLowerCase();
          const display = (p.display_name || '').toLowerCase();
          let rank = 0;
          if (name === q) rank = 4;
          else if (name.startsWith(q)) rank = 3;
          else if (display.includes(q)) rank = 2;
          if (!rank) continue;
          out.push({
            _rank: rank,
            id: `osm:${p.category}${p.id}`, kind: 'place', name: p.name,
            label: p.display_name, level: null, lat: p.lat, lng: p.lon,
            bbox: null, postcode: p.postcode || null,
            category: p.category, type: p.type, region: null,
            score: rank === 4 ? 1 : rank === 3 ? 0.9 : 0.7,
            geometry: null,
          });
        }
      }
      out.sort((a, b) => b._rank - a._rank
        || b.score - a.score
        || (a.kind === 'region' ? -1 : 1));
      const results = out.slice(0, limit).map(({ _rank, ...rest }) => rest);
      return { query: text, count: results.length, results, took_ms: 1.2 };
    }

    function boundary(code) {
      const region = BY.get(String(code));
      if (!region || !region.geometry) {
        throw new Error('Wilayah tidak memiliki polygon');
      }
      return {
        type: 'Feature',
        id: region.code,
        properties: {
          code: region.code,
          name: region.name,
          level: region.level,
          full_name: fullNameOf(region),
          postal_codes: region.postal || [],
        },
        geometry: region.geometry,
      };
    }

    function handle(path, query) {
      if (path.endsWith('/reverse')) {
        return reverse(Number(query.get('lat')), Number(query.get('lng')));
      }
      if (path.endsWith('/search')) {
        return search(
          query.get('q') || '',
          Number(query.get('limit')) || 5,
          query.get('type') || 'all',
          query.get('include_geometry') === 'true',
        );
      }
      if (path.endsWith('/config')) {
        return { country: 'Indonesia', bbox: [94, -12, 142, 7], demo: true };
      }
      const match = path.match(/\/regions\/(\d+)\/boundary$/);
      if (match) return boundary(match[1]);
      throw new Error('Endpoint demo tidak tersedia');
    }

    const realFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const raw = input instanceof URL ? input.href
        : typeof input === 'string' ? input : input.url;
      let url;
      try {
        url = new URL(raw, location.href);
      } catch (_) {
        return realFetch(input, init);
      }
      if (!url.pathname.includes('/api/v1/geo/')) return realFetch(input, init);
      try {
        return Promise.resolve(json(handle(url.pathname, url.searchParams)));
      } catch (error) {
        return Promise.resolve(json({ detail: error.message }, 404));
      }
    };

    const style = document.createElement('style');
    style.textContent = `
      .demo-static-badge{position:fixed;left:14px;bottom:14px;z-index:1100;
        background:rgba(15,118,110,.94);color:#fff;padding:7px 11px;border-radius:999px;
        font:600 11px/1.2 Inter,system-ui,sans-serif;box-shadow:0 6px 18px rgba(15,23,42,.22);
        pointer-events:none;letter-spacing:.01em}
      @media(max-width:640px){.demo-static-badge{bottom:auto;top:74px;left:12px}}`;
    document.head.appendChild(style);
    const addBadge = () => {
      if (document.querySelector('.demo-static-badge')) return;
      const badge = document.createElement('div');
      badge.className = 'demo-static-badge';
      badge.textContent = 'Demo statis · batas BPS + OpenStreetMap';
      document.body.appendChild(badge);
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', addBadge, { once: true });
    } else {
      addBadge();
    }
  }

  if (window.PETA_DEMO_DATA) {
    boot(window.PETA_DEMO_DATA);
  } else {
    const fallback = new URL('demo-data.json', scriptUrl).href;
    fetch(fallback)
      .then((response) => response.json())
      .then(boot)
      .catch(() => {
        window.fetch = () => Promise.resolve(new Response(
          JSON.stringify({ detail: 'Data demo tidak termuat' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } },
        ));
      });
  }
})();
