# Frontend — Peta Location Picker

Widget pemilih lokasi Indonesia yang dapat di-embed ke aplikasi apa pun.
Semua logika peta, pencarian, reverse geocoding, dan overlay batas wilayah
berada di dalam satu file HTML mandiri.

## Isi folder

| File | Fungsi |
| --- | --- |
| `widget/location-picker.html` | Widget mandiri (Leaflet + CSS + JS, tanpa build step) |
| `embed/peta-location-picker.js` | Web Component `<peta-location-picker>` pembungkus iframe |
| `react/LocationPicker.tsx` | Komponen React + TypeScript dengan event bertipe |
| `embed-example.html` | Demo parent: kontrol API/tema, kirim perintah, tampilkan payload |

## Menjalankan demo

```bash
# dari root repo
python3 -m http.server 8080
# buka http://localhost:8080/frontend/embed-example.html
```

API default `http://localhost:8000`. Jalankan backend dan database terlebih
dahulu (lihat README utama), atau ubah nilai **API** di toolbar demo.

## 1. Embed langsung dengan iframe

```html
<iframe
  src="/frontend/widget/location-picker.html?apiBase=https://api.example.id&theme=light"
  title="Pilih lokasi"
  style="width:100%;height:560px;border:0;border-radius:16px"
  allow="geolocation"
  referrerpolicy="strict-origin-when-cross-origin"></iframe>
```

Responsif: di layar sempit panel detail otomatis menjadi bottom sheet.

### Query parameter widget

| Parameter | Default | Keterangan |
| --- | --- | --- |
| `apiBase` | same-origin / `http://localhost:8000` | Base URL API |
| `theme` | `light` / `dark` (prefers-color-scheme) | `light` atau `dark` |
| `lat`, `lng` | — | Posisi pin awal |
| `zoom` | `5` | Zoom awal |
| `tileUrl` | OSM standard | Template tile `{s}/{z}/{x}/{y}` |
| `tileAttribution` | OSM | Atribusi tile |
| `targetOrigin` | `*` | Origin parent penerima pesan |
| `allowedOrigin` | *(kosong)* | Batasi origin parent yang boleh mengirim perintah |
| `autoSelect` | `0` | Kirim `LOCATION_SELECTED` otomatis setelah reverse sukses |
| `readOnly` | `0` | Nonaktifkan klik/geser pin |
| `closeButton` | `0` | Tampilkan tombol tutup (mode modal) |
| `emitOnMove` | `0` | Kirim `PETA_LOCATION_CHANGED` setiap pin bergeser |
| `mode` | — | `modal` menampilkan tombol tutup |

> Gunakan `targetOrigin` dan `allowedOrigin` yang spesifik di produksi.
> `*` memudahkan demo, tetapi tidak memverifikasi asal pesan.

## 2. Web Component

```html
<script src="/frontend/embed/peta-location-picker.js" defer></script>

<peta-location-picker
  id="picker"
  src="/frontend/widget/location-picker.html"
  api-base="https://api.example.id"
  theme="light"
  height="560"
  target-origin="https://app.example.id"
  allowed-origin="https://app.example.id"
  close-button></peta-location-picker>

<script>
  const picker = document.getElementById('picker');
  picker.addEventListener('location-selected', (event) => {
    console.log('Payload:', event.detail);
    // { lat, lng, address, region, postal_code, nearest, match, ... }
  });
  picker.addEventListener('peta-ready', () => {
    picker.setLocation(-6.9175, 107.6191, { zoom: 15 });
  });
</script>
```

Atribut: `src`, `api-base`, `theme`, `lat`, `lng`, `zoom`, `height`, `mode`,
`tile-url`, `tile-attribution`, `target-origin`, `allowed-origin`,
`widget-origin`, `auto-select`, `read-only`, `close-button`, `emit-on-move`.

Method: `setLocation(lat, lng, opts)`, `search(q, opts)`, `configure(cfg)`,
`setTheme(theme)`, `clear()`, `getState()`, `close()`, `reload()`.
Getter: `ready`, `state`.

Event yang dipancarkan: `peta-ready`, `location-selected`,
`peta-location-changed`, `peta-close-request`, `peta-state`, `peta-reset`,
`peta-reload`. Semua `bubbles` dan `composed`.

## 3. React

```tsx
import { useRef } from 'react';
import LocationPicker, {
  type LocationPickerHandle,
  type PetaLocationPayload,
} from './LocationPicker';

export function AddressStep() {
  const picker = useRef<LocationPickerHandle>(null);

  const handleSelect = (payload: PetaLocationPayload) => {
    console.log(payload.formatted_address, payload.lat, payload.lng);
  };

  return (
    <>
      <LocationPicker
        ref={picker}
        apiBase="https://api.example.id"
        height={560}
        theme="light"
        targetOrigin={window.location.origin}
        allowedOrigin={window.location.origin}
        onSelectLocation={handleSelect}
        onCloseRequest={() => picker.current?.close()}
      />
      <button onClick={() => picker.current?.search('Cibaduyut', { selectFirst: true })}>
        Cari Cibaduyut
      </button>
    </>
  );
}
```

Komponen tidak memerlukan build khusus widget: `src` dapat menunjuk ke file
HTML yang di-host terpisah. Jika memakai Vite/Next, salin
`widget/location-picker.html` ke `public/` dan set
`src="/location-picker.html"`.

## 4. Kontrak `postMessage`

Semua pesan berbentuk:

```json
{ "source": "peta-location-picker", "version": "1.0.0", "type": "...", "data": {}, "timestamp": 1730000000000 }
```

### Widget → parent

| Tipe | Kapan | `data` |
| --- | --- | --- |
| `PETA_READY` | Widget selesai init | `{ version, apiBase, capabilities, config }` |
| `LOCATION_SELECTED` | User menekan **Gunakan Lokasi Ini** / `autoSelect` | Payload lokasi |
| `PETA_LOCATION_CHANGED` | Pin bergeser, bila `emitOnMove` | Payload lokasi |
| `PETA_CLOSE_REQUEST` | Tombol tutup / `PETA_CLOSE` | Payload atau `null` |
| `PETA_STATE` | Respons `PETA_GET_STATE` | `{ lat, lng, result, configured }` |
| `PETA_RESET` | `PETA_CLEAR` atau tombol Reset | `null` |

### Parent → widget

| Tipe | `data` |
| --- | --- |
| `PETA_CONFIGURE` | `{ apiBase?, theme?, tileUrl?, tileAttribution?, autoSelect?, readOnly?, closeButton?, emitOnMove?, targetOrigin?, location? }` |
| `PETA_SET_LOCATION` | `{ lat, lng, zoom?, flyTo? }` |
| `PETA_SEARCH` | `{ q, selectFirst? }` |
| `PETA_SET_THEME` | `{ theme: "light" | "dark" }` |
| `PETA_CLEAR` | `null` |
| `PETA_GET_STATE` | `null` |
| `PETA_CLOSE` | `null` |

### Contoh payload `LOCATION_SELECTED`

```json
{
  "lat": -6.946966,
  "lng": 107.598788,
  "location": { "lat": -6.946966, "lng": 107.598788 },
  "address": {
    "line1": "Jalan Cibaduyut 12",
    "street": "Jalan Cibaduyut",
    "housenumber": "12",
    "village": "CIBADUYUT",
    "district": "BOJONGLOA KIDUL",
    "regency": "BANDUNG",
    "province": "JAWA BARAT",
    "postcode": "40236",
    "formatted": "Jalan Cibaduyut 12, CIBADUYUT, BOJONGLOA KIDUL, BANDUNG, JAWA BARAT, 40236",
    "label": "Jalan Cibaduyut 12, Cibaduyut, Bojongloa Kidul, Bandung"
  },
  "region": {
    "province": { "code": "32", "name": "JAWA BARAT" },
    "regency": { "code": "3273", "name": "BANDUNG" },
    "district": { "code": "3273040", "name": "BOJONGLOA KIDUL" },
    "village": { "code": "3273040004", "name": "CIBADUYUT" }
  },
  "postal_code": "40236",
  "formatted_address": "Jalan Cibaduyut 12, CIBADUYUT, ..., 40236",
  "nearest": {
    "road": { "name": "Jalan Cibaduyut", "ref": null, "highway": "residential", "distance_m": 12.4 },
    "place": { "name": "Pasar Cibaduyut", "category": "amenity", "type": "marketplace", "lat": -6.947, "lon": 107.599, "distance_m": 48.2 }
  },
  "match": { "method": "polygon", "level": 4, "approximate": false, "distance_m": 0, "confidence": 0.98 },
  "source": "peta-location-picker",
  "selected_at": "2026-11-09T04:00:00.000Z"
}
```

## 5. Keamanan & produksi

- Set `TARGET_ORIGIN`/`targetOrigin` ke origin aplikasi Anda, bukan `*`.
- Set `allowed-origin` agar widget hanya menerima perintah dari parent tepercaya.
- Verifikasi `event.source` (sudah dilakukan wrapper) dan `event.origin`.
- `postMessage` tidak terpengaruh CORS, tetapi `fetch` dari widget ke API
  terpengaruh. Tambahkan origin widget ke `CORS_ORIGINS` backend.
- Bila API memakai `API_KEYS`, kirim lewat reverse proxy atau sesi server;
  jangan menaruh API key rahasia di query string halaman publik.
- Batasi `RATE_LIMIT_PER_MINUTE` dan pasang HTTPS di produksi.
- Tile OSM memiliki [policy penggunaan](https://operations.osmfoundation.org/policies/tiles/);
  untuk traffic tinggi gunakan penyedia tile sendiri.
