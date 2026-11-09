from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from .api.geo import router as geo_router
from .config import get_settings
from .db import close_pool, healthcheck, init_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("peta-api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_pool()
    log.info("API siap")
    yield
    await close_pool()


settings = get_settings()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
)

app = FastAPI(
    title="Peta Indonesia Geocoding API",
    version="1.0.0",
    description=(
        "API reverse geocoding, autocomplete alamat, dan hierarki wilayah Indonesia "
        "berbasis PostGIS + OpenStreetMap (Geofabrik)."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=800)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.cors_origin_list != ["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time"],
)

app.include_router(geo_router)


@app.middleware("http")
async def observability(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{(time.perf_counter() - started) * 1000:.1f}ms"
    return response


@app.get("/health", tags=["ops"])
async def health() -> JSONResponse:
    try:
        db = await healthcheck()
    except Exception as exc:
        log.exception("Health check gagal")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": str(exc).splitlines()[0]},
        )
    return JSONResponse(
        content={
            "status": "ok",
            "database": "up",
            "postgis": db.get("postgis_version"),
            "db_time": db.get("db_time").isoformat() if db.get("db_time") else None,
            "version": app.version,
        }
    )


@app.get("/api/v1/geo/config", tags=["geocoding"])
async def client_config() -> dict:
    """Konfigurasi ringan untuk widget (basemap, bbox, versi)."""
    return {
        "version": app.version,
        "country": "ID",
        "bbox": [94.0, -12.0, 142.0, 7.0],
        "center": {"lat": -2.5, "lng": 118.0},
        "default_zoom": 5,
        "tile_url": settings.tile_url,
        "tile_attribution": settings.tile_attribution,
        "levels": [
            {"level": 1, "name": "provinsi", "code_length": 2},
            {"level": 2, "name": "kabupaten/kota", "code_length": 4},
            {"level": 3, "name": "kecamatan", "code_length": 7},
            {"level": 4, "name": "kelurahan/desa", "code_length": 10},
        ],
    }
