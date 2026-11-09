/*
 * Demo API statis untuk GitHub Pages. Aktif hanya dengan ?demo=1.
 * Data berasal dari etl/seed_demo.py (area Cibaduyut, Bandung).
 * Tidak menggantikan backend FastAPI/PostGIS; hanya untuk demo UI.
 */
(() => {
  const params = new URLSearchParams(location.search);
  if (params.get('demo') !== '1') return;

  const R = [
    { c: '32', l: 1, n: 'JAWA BARAT', p: null, po: ['40100', '40200'], b: [107.5, -7, 107.75, -6.85], pt: [-6.9033, 107.6426] },
    { c: '3273', l: 2, n: 'BANDUNG', p: '32', po: ['40100', '40200'], b: [107.55, -6.98, 107.72, -6.87], pt: [-6.9033, 107.6426] },
    { c: '3273040', l: 3, n: 'BOJONGLOA KIDUL', p: '3273', po: ['40234', '40235', '40236', '40237', '40238', '40239'], b: [107.585, -6.955, 107.61, -6.94], pt: [-6.947, 107.5988] },
    { c: '3273080', l: 3, n: 'BANDUNG KIDUL', p: '3273', po: ['40266', '40267', '40268', '40269'], b: [107.615, -6.965, 107.645, -6.945], pt: [-6.9559, 107.6296] },
    { c: '3273040004', l: 4, n: 'CIBADUYUT', p: '3273040', po: ['40236'], b: [107.595, -6.95, 107.602, -6.944], pt: [-6.946966, 107.598788] },
    { c: '3273040001', l: 4, n: 'CIBADUYUT KIDUL', p: '3273040', po: ['40239'], b: null, pt: [-6.9475, 107.5965] },
    { c: '3273040002', l: 4, n: 'CIBADUYUT WETAN', p: '3273040', po: ['40238'], b: null, pt: [-6.946, 107.601] },
    { c: '3273080001', l: 4, n: 'BATUNUNGGAL', p: '3273080', po: ['40266'], b: null, pt: [-6.9559, 107.6296] },
  ];

  const P = [
    { t: 'n', id: 900000001, n: 'Pasar Cibaduyut', d: 'Pasar Cibaduyut, Bojongloa Kidul, Bandung', cat: 'amenity', typ: 'marketplace', lat: -6.947, lon: 107.598, pc: '40236' },
    { t: 'n', id: 900000002, n: 'Cibaduyut', d: 'Cibaduyut, Bojongloa Kidul, Bandung, Jawa Barat', cat: 'place', typ: 'village', lat: -6.946966, lon: 107.598788, pc: '40236' },
    { t: 'n', id: 900000003, n: 'Bandung', d: 'Bandung, Jawa Barat, Indonesia', cat: 'place', typ: 'city', lat: -6.9033, lon: 107.6426, pc: null },
    { t: 'n', id: 900000004, n: 'Toko Sepatu Cibaduyut', d: 'Toko Sepatu Cibaduyut, Jalan Cibaduyut, Bandung', cat: 'shop', typ: 'shoes', lat: -6.9465, lon: 107.5977, pc: '40236' },
  ];

  const ROADS = [
    { n: 'Jalan Cibaduyut', ref: null, hw: 'residential', pts: [[-6.951, 107.5978], [-6.947, 107.5982], [-6.943, 107.599]] },
    { n: 'Jalan Soekarno-Hatta', ref: 'AH2', hw: 'trunk', pts: [[-6.94, 107.58], [-6.942, 107.6], [-6.944, 107.62]] },
    { n: 'Jalan Kopo', ref: null, hw: 'primary', pts: [[-6.96, 107.585], [-6.95, 107.59], [-6.94, 107.595]] },
  ];

  const BY = new Map(R.map((r) => [r.c, r]));
  const LVL = ['', 'province', 'regency', 'district', 'village'];
  const json = (data, status = 200) => new Response(JSON.stringify(data), {
    status, headers: { 'Content-Type': 'application/json' },
  });
  const rad = (d) => (d * Math.PI) / 180;
  const hav = (a, b, c, d) => {
    const dLat = rad(c - a), dLng = rad(d - b);
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a)) * Math.cos(rad(c)) * Math.sin(dLng / 2) ** 2;
    return 6371008.8 * 2 * Math.asin(Math.sqrt(h));
  };
  const area = (r) => r.b ? (r.b[2] - r.b[0]) * (r.b[3] - r.b[1]) : 0;
  const poly = (b) => ({ type: 'Polygon', coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]] });

  function chainOf(r) {
    const out = { province: null, regency: null, district: null, village: null };
    let cur = r;
    while (cur) {
      if (!out[LVL[cur.l]]) out[LVL[cur.l]] = { code: cur.c, name: cur.n };
      cur = BY.get(cur.p);
    }
    return out;
  }
  const labelOf = (r) => {
    const ch = chainOf(r);
    return [ch.village, ch.district, ch.regency, ch.province].filter(Boolean).map((x) => x.name).join(', ');
  };

  function segDist(lat, lng, a, b) {
    const k = Math.cos(rad(lat));
    const px = (lng - a[1]) * k, py = lat - a[0];
    const dx = (b[1] - a[1]) * k, dy = b[0] - a[0];
    const len = dx * dx + dy * dy;
    const t = len ? Math.max(0, Math.min(1, (px * dx + py * dy) / len)) : 0;
    return Math.hypot(px - t * dx, py - t * dy) * 111320;
  }

  function nearest(lat, lng) {
    let road = null, rd = Infinity;
    for (const r of ROADS) {
      for (let i = 1; i < r.pts.length; i += 1) {
        const d = segDist(lat, lng, r.pts[i - 1], r.pts[i]);
        if (d < rd) { rd = d; road = r; }
      }
    }
    let place = null, pd = Infinity;
    for (const p of P) {
      const d = hav(lat, lng, p.lat, p.lon);
      if (d < pd) { pd = d; place = p; }
    }
    return {
      road: road && rd <= 250 ? { name: road.n, ref: road.ref, highway: road.hw, distance_m: Math.round(rd * 10) / 10 } : null,
      place: place && pd <= 300 ? { name: place.n, category: place.cat, type: place.typ, lat: place.lat, lon: place.lon, distance_m: Math.round(pd * 10) / 10 } : null,
      placeRow: place && pd <= 300 ? place : null,
    };
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const raw = input instanceof URL ? input.href : typeof input === 'string' ? input : input.url;
    let url;
    try { url = new URL(raw, location.href); } catch (_) { return realFetch(input, init); }
    if (!url.pathname.includes('/api/v1/geo/')) return realFetch(input, init);
    try {
      return Promise.resolve(json(handle(url.pathname, url.searchParams)));
    } catch (error) {
      return Promise.resolve(json({ detail: error.message }, 404));
    }
  };

  function handle(path, q) {
    if (path.endsWith('/reverse')) return reverse(Number(q.get('lat')), Number(q.get('lng')));
    if (path.endsWith('/search')) return search(q.get('q') || '', Number(q.get('limit')) || 5, q.get('type') || 'all', q.get('include_geometry') === 'true');
    if (path.endsWith('/config')) return { country: 'Indonesia', bbox: [94, -12, 142, 7], demo: true };
    const m = path.match(/\/regions\/(\d+)\/boundary$/);
    if (m) return boundary(m[1]);
    throw new Error('Endpoint demo tidak tersedia');
  }

  function reverse(lat, lng) {
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) throw new Error('Koordinat tidak valid');
    let hit = null;
    for (const r of R) {
      if (!r.b) continue;
      const [w, s, e, n] = r.b;
      if (lng >= w && lng <= e && lat >= s && lat <= n) {
        if (!hit || r.l > hit.l || (r.l === hit.l && area(r) < area(hit))) hit = r;
      }
    }
    let approx = false, dist = 0;
    if (!hit) {
      let best = null, bd = Infinity;
      for (const r of R) {
        if (!r.b) continue;
        const [w, s, e, n] = r.b;
        const d = hav(lat, lng, (s + n) / 2, (w + e) / 2);
        if (d < bd) { bd = d; best = r; }
      }
      if (!best || bd > 25000) return { found: false, reason: 'no_result', location: { lat, lng } };
      hit = best; approx = true; dist = bd;
    }

    const ch = chainOf(hit);
    const fill = (level, parentCode) => {
      const key = LVL[level];
      if (ch[key] || !parentCode) return;
      let best = null, bd = Infinity;
      for (const r of R) {
        if (r.l !== level) continue;
        const parent = r.c.slice(0, { 2: 2, 3: 4, 4: 7 }[level]);
        if (parent !== parentCode) continue;
        const d = hav(lat, lng, r.pt[0], r.pt[1]);
        if (d < bd) { bd = d; best = r; }
      }
      if (best) {
        ch[key] = { code: best.c, name: best.n };
        approx = true;
        if (level === 4) dist = bd;
      }
    };
    if (ch.province) fill(2, ch.province.code);
    if (ch.regency) fill(3, ch.regency.code);
    if (ch.district) fill(4, ch.district.code);

    const near = nearest(lat, lng);
    const deepest = ch.village || ch.district || ch.regency || ch.province;
    const postcode = near.placeRow?.pc || R.find((r) => r.c === deepest?.code)?.po?.[0] || null;
    const parts = [ch.village, ch.district, ch.regency, ch.province].filter(Boolean).map((x) => x.name);
    const label = parts.join(', ');
    const line1 = near.road?.name || near.place?.name || null;
    const formatted = [line1, ...parts, postcode].filter(Boolean).join(', ');
    const level = ch.village ? 4 : ch.district ? 3 : ch.regency ? 2 : 1;
    const confidence = level === 4 ? (approx ? 0.8 : 0.98) : level === 3 ? 0.65 : level === 2 ? 0.5 : 0.3;

    return {
      found: true,
      location: { lat, lng },
      region: ch,
      address: {
        line1,
        street: near.road?.name || null,
        housenumber: null,
        village: ch.village?.name || null,
        district: ch.district?.name || null,
        regency: ch.regency?.name || null,
        province: ch.province?.name || null,
        postcode,
        formatted,
        label,
      },
      nearest: { road: near.road, place: near.place },
      match: {
        method: approx ? 'nearest' : 'polygon',
        level: hit.l,
        approximate: approx,
        distance_m: Math.round(dist * 10) / 10,
        confidence,
      },
      source: 'demo+static',
    };
  }

  function search(text, limit, type, withGeom) {
    const q = text.trim().toLowerCase();
    if (!q) return { query: text, count: 0, results: [], took_ms: 0 };
    const out = [];
    if (type !== 'place') {
      for (const r of R) {
        const name = r.n.toLowerCase(), full = labelOf(r).toLowerCase();
        let rank = 0;
        if (name === q) rank = 4;
        else if (name.startsWith(q)) rank = 3;
        else if (full.includes(q)) rank = 2;
        else if (r.c.startsWith(q)) rank = 1;
        if (!rank) continue;
        out.push({
          _r: rank,
          id: r.c, kind: 'region', name: r.n, label: labelOf(r), level: r.l,
          lat: r.pt[0], lng: r.pt[1], bbox: r.b, postcode: r.po?.[0] || null,
          category: null, type: null, region: chainOf(r),
          score: rank === 4 ? 1 : rank === 3 ? 0.9 : rank === 2 ? 0.7 : 0.55,
          geometry: withGeom && r.b ? poly(r.b) : null,
        });
      }
    }
    if (type !== 'region') {
      for (const p of P) {
        const name = p.n.toLowerCase(), disp = (p.d || '').toLowerCase();
        let rank = 0;
        if (name === q) rank = 4;
        else if (name.startsWith(q)) rank = 3;
        else if (disp.includes(q)) rank = 2;
        if (!rank) continue;
        out.push({
          _r: rank,
          id: `osm:${p.t}${p.id}`, kind: 'place', name: p.n, label: p.d, level: null,
          lat: p.lat, lng: p.lon, bbox: null, postcode: p.pc || null,
          category: p.cat, type: p.typ, region: null,
          score: rank === 4 ? 1 : rank === 3 ? 0.9 : 0.7,
          geometry: null,
        });
      }
    }
    out.sort((a, b) => b._r - a._r || b.score - a.score || (a.kind === 'region' ? -1 : 1));
    const results = out.slice(0, limit).map(({ _r, ...rest }) => rest);
    return { query: text, count: results.length, results, took_ms: 1.2 };
  }

  function boundary(code) {
    const r = BY.get(code);
    if (!r || !r.b) throw new Error('Wilayah tidak memiliki polygon');
    return {
      type: 'Feature',
      id: r.c,
      properties: { code: r.c, name: r.n, level: r.l, full_name: labelOf(r), postal_codes: r.po || [] },
      geometry: poly(r.b),
    };
  }

  const style = document.createElement('style');
  style.textContent = `
    .demo-static-badge{position:fixed;left:14px;bottom:14px;z-index:1100;
      background:rgba(15,118,110,.94);color:#fff;padding:7px 11px;border-radius:999px;
      font:600 11px/1.2 Inter,system-ui,sans-serif;box-shadow:0 6px 18px rgba(15,23,42,.22);
      pointer-events:none;letter-spacing:.01em}
    @media(max-width:640px){.demo-static-badge{bottom:auto;top:74px;left:12px}}`;
  document.head.appendChild(style);
  document.addEventListener('DOMContentLoaded', () => {
    const badge = document.createElement('div');
    badge.className = 'demo-static-badge';
    badge.textContent = 'Demo statis · data contoh Bandung';
    document.body.appendChild(badge);
  });
})();

