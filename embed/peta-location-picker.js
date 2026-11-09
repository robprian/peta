/*!
 * <peta-location-picker> — Web Component wrapper for the Peta location picker.
 * ---------------------------------------------------------------------------
 * Usage:
 *   <script src="/frontend/embed/peta-location-picker.js" defer></script>
 *   <peta-location-picker api-base="https://api.example.id" theme="light"></peta-location-picker>
 *
 * Events (bubble + composed):
 *   peta-ready, location-selected, peta-location-changed,
 *   peta-close-request, peta-state, peta-reset, peta-reload
 *
 * API: setLocation, search, configure, setTheme, clear, getState, close, reload
 */
(function (global) {
  'use strict';
  if (!global || !global.document) return;

  var MESSAGE_SOURCE = 'peta-location-picker';
  var SCRIPT_URL = (document.currentScript && document.currentScript.src) || '';
  var DEFAULT_SRC = SCRIPT_URL
    ? new URL('../widget/location-picker.html', SCRIPT_URL).href
    : 'widget/location-picker.html';

  var OBSERVED = [
    'src', 'api-base', 'theme', 'lat', 'lng', 'zoom', 'height', 'mode',
    'tile-url', 'tile-attribution', 'target-origin', 'allowed-origin',
    'widget-origin', 'auto-select', 'read-only', 'close-button', 'emit-on-move'
  ];

  var EVENT_MAP = {
    PETA_READY: 'peta-ready',
    LOCATION_SELECTED: 'location-selected',
    PETA_LOCATION_CHANGED: 'peta-location-changed',
    PETA_CLOSE_REQUEST: 'peta-close-request',
    PETA_STATE: 'peta-state',
    PETA_RESET: 'peta-reset'
  };

  var CONFIG_MAP = {
    apiBase: 'api-base',
    theme: 'theme',
    tileUrl: 'tile-url',
    tileAttribution: 'tile-attribution',
    targetOrigin: 'target-origin',
    allowedOrigin: 'allowed-origin',
    mode: 'mode'
  };

  var BOOL_MAP = {
    autoSelect: 'auto-select',
    readOnly: 'read-only',
    closeButton: 'close-button',
    emitOnMove: 'emit-on-move'
  };

  function numberAttr(el, name) {
    var raw = el.getAttribute(name);
    if (raw === null || raw === '') return null;
    var value = Number(raw);
    return Number.isFinite(value) ? value : null;
  }

  function flagAttr(el, name) {
    var raw = el.getAttribute(name);
    return raw !== null && raw !== 'false' && raw !== '0';
  }

  class PetaLocationPicker extends HTMLElement {
    static get observedAttributes() { return OBSERVED; }

    constructor() {
      super();
      this._iframe = null;
      this._ready = false;
      this._queue = [];
      this._state = null;
      this._lastLocation = '';
      this._initialized = false;
      this._onMessage = this._onMessage.bind(this);
      this._onLoad = this._onLoad.bind(this);
    }

    connectedCallback() {
      if (!this._initialized) this._render();
      global.addEventListener('message', this._onMessage);
    }

    disconnectedCallback() {
      global.removeEventListener('message', this._onMessage);
    }

    attributeChangedCallback(name, oldValue, newValue) {
      if (oldValue === newValue || !this._initialized) return;
      if (name === 'src' || name === 'widget-origin') { this.reload(); return; }
      if (name === 'height') { this._applyHeight(); return; }
      if (name === 'lat' || name === 'lng' || name === 'zoom') {
        this._applyLocation(false);
        return;
      }
      this._send('PETA_CONFIGURE', this._config());
    }

    get ready() { return this._ready; }
    get state() { return this._state; }

    _render() {
      var root = this.attachShadow ? this.attachShadow({ mode: 'open' }) : this;
      var style = document.createElement('style');
      style.textContent = [
        ':host{display:block;position:relative;width:100%;height:var(--peta-height,520px);',
        'border-radius:var(--peta-radius,16px);overflow:hidden;background:#eef2f3;isolation:isolate}',
        'iframe{display:block;width:100%;height:100%;border:0;background:#eef2f3}'
      ].join('');
      var frame = document.createElement('iframe');
      frame.setAttribute('title', this.getAttribute('title') || 'Pemilih lokasi Indonesia');
      frame.setAttribute('aria-label', this.getAttribute('title') || 'Pemilih lokasi Indonesia');
      frame.setAttribute('allow', 'geolocation; fullscreen');
      frame.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
      frame.setAttribute('loading', 'eager');
      frame.addEventListener('load', this._onLoad);
      root.appendChild(style);
      root.appendChild(frame);
      this._iframe = frame;
      this._applyHeight();
      this._initialized = true;
      frame.src = this._buildSrc();
    }

    _applyHeight() {
      if (!this._iframe) return;
      var raw = this.getAttribute('height');
      var value = !raw ? '520px' : (/^\d+$/.test(raw) ? raw + 'px' : raw);
      this.style.setProperty('--peta-height', value);
      this._iframe.style.height = '100%';
    }

    _buildSrc() {
      var url = new URL(this.getAttribute('src') || DEFAULT_SRC, document.baseURI);
      var params = {
        apiBase: this.getAttribute('api-base'),
        theme: this.getAttribute('theme'),
        tileUrl: this.getAttribute('tile-url'),
        tileAttribution: this.getAttribute('tile-attribution'),
        targetOrigin: this.getAttribute('target-origin'),
        allowedOrigin: this.getAttribute('allowed-origin'),
        mode: this.getAttribute('mode'),
        lat: this.getAttribute('lat'),
        lng: this.getAttribute('lng'),
        zoom: this.getAttribute('zoom')
      };
      Object.keys(params).forEach(function (key) {
        var value = params[key];
        if (value !== null && value !== '' && !(key === 'theme' && value === 'auto')) {
          url.searchParams.set(key, value);
        }
      });
      this._boolParams(url);
      return url.href;
    }

    _boolParams(url) {
      var self = this;
      Object.keys(BOOL_MAP).forEach(function (key) {
        if (flagAttr(self, BOOL_MAP[key])) url.searchParams.set(key, '1');
      });
    }

    _config() {
      var cfg = {};
      var self = this;
      Object.keys(CONFIG_MAP).forEach(function (key) {
        var value = self.getAttribute(CONFIG_MAP[key]);
        if (value !== null && value !== '' && !(key === 'theme' && value === 'auto')) {
          cfg[key] = value;
        }
      });
      Object.keys(BOOL_MAP).forEach(function (key) {
        if (self.hasAttribute(BOOL_MAP[key])) cfg[key] = flagAttr(self, BOOL_MAP[key]);
      });
      return cfg;
    }

    _widgetOrigin() {
      var explicit = this.getAttribute('widget-origin');
      if (explicit) return explicit;
      try {
        var origin = new URL(this._iframe ? this._iframe.src : this._buildSrc(), document.baseURI).origin;
        return origin && origin !== 'null' ? origin : '*';
      } catch (_) {
        return '*';
      }
    }

    _post(type, data) {
      if (!this._iframe || !this._iframe.contentWindow) return;
      try {
        this._iframe.contentWindow.postMessage({ type: type, data: data }, this._widgetOrigin());
      } catch (error) {
        if (global.console) console.warn('[peta] postMessage gagal', error);
      }
    }

    _send(type, data) {
      if (!this._ready) {
        this._queue.push([type, data]);
        return;
      }
      this._post(type, data);
    }

    _flush() {
      var queue = this._queue.splice(0, this._queue.length);
      for (var i = 0; i < queue.length; i += 1) this._post(queue[i][0], queue[i][1]);
      var cfg = this._config();
      if (Object.keys(cfg).length) this._post('PETA_CONFIGURE', cfg);
    }

    _onLoad() {
      this._ready = false;
      var self = this;
      // Handshake fallback if PETA_READY was missed (e.g. listener attached late).
      global.setTimeout(function () {
        if (!self._ready) self._post('PETA_GET_STATE', null);
      }, 1200);
    }

    _onMessage(event) {
      if (!this._iframe || event.source !== this._iframe.contentWindow) return;
      var message = event.data;
      if (!message || message.source !== MESSAGE_SOURCE || typeof message.type !== 'string') return;

      var allowed = this.getAttribute('allowed-origin');
      if (allowed && event.origin !== allowed) return;

      if (message.type === 'PETA_READY') {
        this._ready = true;
        this._lastLocation = this._locationKey();
        this._flush();
      } else if (message.type === 'PETA_STATE') {
        this._state = message.data;
      } else if (message.type === 'PETA_RESET') {
        this._state = null;
      }

      var eventName = EVENT_MAP[message.type];
      if (eventName) {
        this.dispatchEvent(new CustomEvent(eventName, {
          detail: message.data,
          bubbles: true,
          composed: true
        }));
      }
    }

    _locationKey() {
      var lat = numberAttr(this, 'lat');
      var lng = numberAttr(this, 'lng');
      var zoom = numberAttr(this, 'zoom');
      return lat === null || lng === null ? '' : lat + ',' + lng + ',' + (zoom === null ? '' : zoom);
    }

    _applyLocation(force) {
      var lat = numberAttr(this, 'lat');
      var lng = numberAttr(this, 'lng');
      if (lat === null || lng === null) return;
      var key = this._locationKey();
      if (!force && key === this._lastLocation) return;
      this._lastLocation = key;
      var payload = { lat: lat, lng: lng, flyTo: true };
      var zoom = numberAttr(this, 'zoom');
      if (zoom !== null) payload.zoom = zoom;
      this._send('PETA_SET_LOCATION', payload);
    }

    reload() {
      if (!this._iframe) return;
      this._ready = false;
      this._queue = [];
      this._lastLocation = '';
      this._iframe.src = this._buildSrc();
      this.dispatchEvent(new CustomEvent('peta-reload', { detail: null, bubbles: true, composed: true }));
    }

    setLocation(lat, lng, options) {
      var payload = Object.assign({ lat: Number(lat), lng: Number(lng) }, options || {});
      if (!Number.isFinite(payload.lat) || !Number.isFinite(payload.lng)) return this;
      this._send('PETA_SET_LOCATION', payload);
      return this;
    }

    search(query, options) {
      if (query === undefined || query === null) return this;
      var payload = typeof query === 'string'
        ? Object.assign({ q: query }, options || {})
        : Object.assign({}, query, options || {});
      if (payload.q) this._send('PETA_SEARCH', payload);
      return this;
    }

    configure(patch) {
      if (!patch || typeof patch !== 'object') return this;
      var payload = Object.assign({}, patch);
      var point = payload.location || (payload.lat !== undefined ? payload : null);
      if (point && Number.isFinite(Number(point.lat)) && Number.isFinite(Number(point.lng))) {
        this.setLocation(point.lat, point.lng, {
          zoom: payload.zoom,
          flyTo: payload.flyTo !== false
        });
        delete payload.location;
        delete payload.lat;
        delete payload.lng;
        delete payload.latitude;
        delete payload.longitude;
        delete payload.zoom;
        delete payload.flyTo;
      }
      if (Object.keys(payload).length) this._send('PETA_CONFIGURE', payload);
      return this;
    }

    setTheme(theme) {
      this._send('PETA_SET_THEME', { theme: theme });
      return this;
    }

    clear() {
      this._send('PETA_CLEAR', null);
      this._state = null;
      return this;
    }

    getState() {
      this._send('PETA_GET_STATE', null);
      return this;
    }

    close() {
      this._send('PETA_CLOSE', null);
      return this;
    }
  }

  if (!global.customElements.get('peta-location-picker')) {
    global.customElements.define('peta-location-picker', PetaLocationPicker);
  }
  global.PetaLocationPicker = PetaLocationPicker;
})(typeof window !== 'undefined' ? window : this);
