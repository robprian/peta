/**
 * <LocationPicker /> — React wrapper for the Peta location picker widget.
 *
 * The widget is a standalone HTML file, so this component only owns the
 * iframe, the postMessage handshake, and typed props/events.
 */
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  type CSSProperties,
  type SyntheticEvent,
} from 'react';

export interface PetaRegionRef { code: string; name: string }

export interface PetaRegionChain {
  province: PetaRegionRef | null;
  regency: PetaRegionRef | null;
  district: PetaRegionRef | null;
  village: PetaRegionRef | null;
}

export interface PetaAddress {
  line1?: string | null;
  street?: string | null;
  housenumber?: string | null;
  village?: string | null;
  district?: string | null;
  regency?: string | null;
  province?: string | null;
  postcode?: string | null;
  formatted?: string | null;
  label?: string | null;
  [key: string]: unknown;
}

export interface PetaNearestRoad {
  name: string;
  ref?: string | null;
  highway?: string | null;
  distance_m?: number | null;
}

export interface PetaNearestPlace {
  name: string;
  category?: string | null;
  type?: string | null;
  lat?: number | null;
  lon?: number | null;
  distance_m?: number | null;
}

export interface PetaMatchInfo {
  method: 'polygon' | 'nearest' | 'none';
  level?: number | null;
  approximate?: boolean;
  distance_m?: number | null;
  confidence?: number | null;
}

export interface PetaLocationPayload {
  lat: number;
  lng: number;
  location: { lat: number; lng: number };
  address: PetaAddress;
  region: PetaRegionChain | null;
  postal_code: string | null;
  formatted_address: string;
  nearest: { road: PetaNearestRoad | null; place: PetaNearestPlace | null } | null;
  match: PetaMatchInfo | null;
  source: 'peta-location-picker';
  selected_at: string;
  auto?: boolean;
}

export interface PetaReadyInfo {
  version: string;
  apiBase: string;
  capabilities: string[];
  config: { theme: string; closeButton: boolean };
}

export interface PetaState {
  lat: number | null;
  lng: number | null;
  result: unknown;
  configured: Record<string, unknown>;
}

export interface PetaWidgetConfig {
  apiBase?: string;
  theme?: 'light' | 'dark';
  tileUrl?: string;
  tileAttribution?: string;
  targetOrigin?: string;
  allowedOrigin?: string;
  autoSelect?: boolean;
  readOnly?: boolean;
  closeButton?: boolean;
  emitOnMove?: boolean;
  mode?: string;
}

export interface PetaSetLocationOptions {
  zoom?: number;
  flyTo?: boolean;
  skipBoundary?: boolean;
}

export interface PetaSearchOptions {
  selectFirst?: boolean;
}

export interface LocationPickerProps {
  /** Widget URL. Defaults to `/frontend/widget/location-picker.html`. */
  src?: string;
  apiBase?: string;
  theme?: 'light' | 'dark' | 'auto';
  /** Initial pin position. Changes after mount fly the map to the new point. */
  lat?: number;
  lng?: number;
  zoom?: number;
  height?: number | string;
  /** Origin that receives widget messages; use your exact parent origin in production. */
  targetOrigin?: string;
  /** Origin allowed to send commands into the widget. */
  allowedOrigin?: string;
  /** Origin used when the parent posts commands to the iframe. */
  widgetOrigin?: string;
  tileUrl?: string;
  tileAttribution?: string;
  autoSelect?: boolean;
  readOnly?: boolean;
  closeButton?: boolean;
  emitOnMove?: boolean;
  mode?: string;
  title?: string;
  className?: string;
  style?: CSSProperties;
  iframeStyle?: CSSProperties;
  onReady?: (info: PetaReadyInfo) => void;
  onSelectLocation?: (payload: PetaLocationPayload) => void;
  onLocationChange?: (payload: PetaLocationPayload) => void;
  onCloseRequest?: (payload: PetaLocationPayload | null) => void;
  onState?: (state: PetaState) => void;
  onReset?: () => void;
  onLoad?: () => void;
  onError?: (event: SyntheticEvent<HTMLIFrameElement>) => void;
}

export interface LocationPickerHandle {
  readonly ready: boolean;
  readonly element: HTMLIFrameElement | null;
  setLocation(lat: number, lng: number, options?: PetaSetLocationOptions): void;
  search(query: string | { q: string; selectFirst?: boolean }, options?: PetaSearchOptions): void;
  configure(config: PetaWidgetConfig): void;
  setTheme(theme: 'light' | 'dark'): void;
  clear(): void;
  getState(): void;
  close(): void;
  reload(): void;
}

type Message = {
  source?: string;
  version?: string;
  type?: string;
  data?: unknown;
};

function buildSrc(props: LocationPickerProps): string {
  const base = props.src || '/frontend/widget/location-picker.html';
  const url = new URL(base, typeof document === 'undefined' ? 'http://localhost/' : document.baseURI);
  const params: Record<string, string | number | null | undefined> = {
    apiBase: props.apiBase,
    theme: props.theme === 'auto' ? undefined : props.theme,
    lat: props.lat,
    lng: props.lng,
    zoom: props.zoom,
    tileUrl: props.tileUrl,
    tileAttribution: props.tileAttribution,
    targetOrigin: props.targetOrigin,
    allowedOrigin: props.allowedOrigin,
    mode: props.mode,
  };
  (Object.keys(params) as Array<keyof typeof params>).forEach((key) => {
    const value = params[key];
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  });
  if (props.autoSelect) url.searchParams.set('autoSelect', '1');
  if (props.readOnly) url.searchParams.set('readOnly', '1');
  if (props.closeButton) url.searchParams.set('closeButton', '1');
  if (props.emitOnMove) url.searchParams.set('emitOnMove', '1');
  return url.href;
}

function locationKey(lat?: number, lng?: number, zoom?: number): string {
  return lat === undefined || lng === undefined ? '' : `${lat},${lng},${zoom ?? ''}`;
}

export const LocationPicker = forwardRef<LocationPickerHandle, LocationPickerProps>(
  function LocationPicker(props, ref) {
    const iframeRef = useRef<HTMLIFrameElement | null>(null);
    const readyRef = useRef(false);
    const pendingRef = useRef<Array<{ type: string; data: unknown }>>([]);
    const handlersRef = useRef(props);
    handlersRef.current = props;

    const src = useMemo(() => buildSrc(props), [
      props.src, props.apiBase, props.theme, props.lat, props.lng, props.zoom,
      props.tileUrl, props.tileAttribution, props.targetOrigin, props.allowedOrigin,
      props.mode, props.autoSelect, props.readOnly, props.closeButton, props.emitOnMove,
    ]);

    const widgetOrigin = useMemo(() => {
      if (props.widgetOrigin) return props.widgetOrigin;
      try {
        const origin = new URL(src, document.baseURI).origin;
        return origin && origin !== 'null' ? origin : '*';
      } catch (_) {
        return '*';
      }
    }, [src, props.widgetOrigin]);

    const post = useMemo(() => (type: string, data: unknown) => {
      const win = iframeRef.current?.contentWindow;
      if (!win) return;
      if (!readyRef.current) {
        pendingRef.current.push({ type, data });
        return;
      }
      win.postMessage({ type, data }, widgetOrigin);
    }, [widgetOrigin]);

    const configFromProps = useMemo(() => {
      const cfg: Record<string, unknown> = {};
      if (props.apiBase) cfg.apiBase = props.apiBase;
      if (props.theme && props.theme !== 'auto') cfg.theme = props.theme;
      if (props.tileUrl) cfg.tileUrl = props.tileUrl;
      if (props.tileAttribution) cfg.tileAttribution = props.tileAttribution;
      if (props.targetOrigin) cfg.targetOrigin = props.targetOrigin;
      if (props.allowedOrigin) cfg.allowedOrigin = props.allowedOrigin;
      if (props.mode) cfg.mode = props.mode;
      if (props.autoSelect !== undefined) cfg.autoSelect = props.autoSelect;
      if (props.readOnly !== undefined) cfg.readOnly = props.readOnly;
      if (props.closeButton !== undefined) cfg.closeButton = props.closeButton;
      if (props.emitOnMove !== undefined) cfg.emitOnMove = props.emitOnMove;
      return cfg;
    }, [
      props.apiBase, props.theme, props.tileUrl, props.tileAttribution,
      props.targetOrigin, props.allowedOrigin, props.mode, props.autoSelect,
      props.readOnly, props.closeButton, props.emitOnMove,
    ]);

    const lastLocationRef = useRef(locationKey(props.lat, props.lng, props.zoom));

    useEffect(() => {
      readyRef.current = false;
      pendingRef.current = [];
      lastLocationRef.current = locationKey(props.lat, props.lng, props.zoom);
      // Only reset when the iframe document itself changes.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [src]);

    useEffect(() => {
      const key = locationKey(props.lat, props.lng, props.zoom);
      if (!key || key === lastLocationRef.current) return;
      lastLocationRef.current = key;
      post('PETA_SET_LOCATION', {
        lat: props.lat,
        lng: props.lng,
        zoom: props.zoom,
        flyTo: true,
      });
    }, [props.lat, props.lng, props.zoom, post]);

    useEffect(() => {
      if (!readyRef.current) return;
      if (Object.keys(configFromProps).length) post('PETA_CONFIGURE', configFromProps);
    }, [configFromProps, post]);

    useEffect(() => {
      const onMessage = (event: MessageEvent) => {
        const frame = iframeRef.current;
        if (!frame || event.source !== frame.contentWindow) return;
        const allowed = handlersRef.current.allowedOrigin;
        if (allowed && event.origin !== allowed) return;
        const message = event.data as Message | null;
        if (!message || message.source !== 'peta-location-picker') return;
        const h = handlersRef.current;

        switch (message.type) {
          case 'PETA_READY':
            readyRef.current = true;
            h.onReady?.(message.data as PetaReadyInfo);
            pendingRef.current.splice(0).forEach((item) => post(item.type, item.data));
            if (Object.keys(configFromProps).length) post('PETA_CONFIGURE', configFromProps);
            break;
          case 'LOCATION_SELECTED':
            h.onSelectLocation?.(message.data as PetaLocationPayload);
            break;
          case 'PETA_LOCATION_CHANGED':
            h.onLocationChange?.(message.data as PetaLocationPayload);
            break;
          case 'PETA_CLOSE_REQUEST':
            h.onCloseRequest?.((message.data ?? null) as PetaLocationPayload | null);
            break;
          case 'PETA_STATE':
            h.onState?.(message.data as PetaState);
            break;
          case 'PETA_RESET':
            h.onReset?.();
            break;
          default:
            break;
        }
      };
      window.addEventListener('message', onMessage);
      return () => window.removeEventListener('message', onMessage);
    }, [configFromProps, post]);

    useImperativeHandle(ref, () => ({
      get ready() { return readyRef.current; },
      get element() { return iframeRef.current; },
      setLocation(lat: number, lng: number, options?: PetaSetLocationOptions) {
        post('PETA_SET_LOCATION', { lat, lng, flyTo: true, ...options });
      },
      search(query, options?: PetaSearchOptions) {
        const payload = typeof query === 'string'
          ? { q: query, ...options }
          : { ...query, ...options };
        if (payload.q) post('PETA_SEARCH', payload);
      },
      configure(config: PetaWidgetConfig) {
        if (config && Object.keys(config).length) post('PETA_CONFIGURE', config);
      },
      setTheme(theme: 'light' | 'dark') {
        post('PETA_SET_THEME', { theme });
      },
      clear() {
        post('PETA_CLEAR', null);
      },
      getState() {
        post('PETA_GET_STATE', null);
      },
      close() {
        post('PETA_CLOSE', null);
      },
      reload() {
        readyRef.current = false;
        pendingRef.current = [];
        lastLocationRef.current = '';
        if (iframeRef.current) iframeRef.current.src = src;
      },
    }), [post, src]);

    const height = typeof props.height === 'number' ? `${props.height}px` : props.height || '520px';

    return (
      <div
        className={props.className}
        style={{ position: 'relative', width: '100%', height, overflow: 'hidden', ...props.style }}
      >
        <iframe
          ref={iframeRef}
          src={src}
          title={props.title || 'Pemilih lokasi Indonesia'}
          allow="geolocation; fullscreen"
          referrerPolicy="strict-origin-when-cross-origin"
          style={{
            display: 'block', width: '100%', height: '100%', border: 0,
            background: '#eef2f3', ...props.iframeStyle,
          }}
          onLoad={() => {
            readyRef.current = false;
            handlersRef.current.onLoad?.();
            window.setTimeout(() => {
              if (!readyRef.current) post('PETA_GET_STATE', null);
            }, 1200);
          }}
          onError={props.onError}
        />
      </div>
    );
  }
);

LocationPicker.displayName = 'LocationPicker';
export default LocationPicker;
