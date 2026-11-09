from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

from ..config import get_settings
from ..schemas import HierarchyResponse, ReverseResponse, SearchResponse
from ..services import geocode, regions, search


async def api_key_guard(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    keys = get_settings().api_key_set
    if not keys:
        return
    token = x_api_key or request.query_params.get("api_key")
    if token not in keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key tidak valid. Kirim header X-API-Key.",
        )


router = APIRouter(
    prefix="/api/v1/geo",
    tags=["geocoding"],
    dependencies=[Depends(api_key_guard)],
)


@router.get("/reverse", response_model=ReverseResponse)
async def reverse(
    response: Response,
    lat: float = Query(..., ge=-90, le=90, description="Latitude WGS84"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude WGS84"),
    refresh: bool = Query(False, description="Lewati cache"),
) -> dict:
    """Reverse geocode: hierarki wilayah + jalan/POI + alamat terformat."""
    if not geocode.in_indonesia(lat, lng):
        raise HTTPException(
            status_code=422,
            detail="Koordinat di luar bounding box Indonesia (94..142 BT, -12..7 LS).",
        )
    result = await geocode.reverse_geocode(lat, lng, use_cache=not refresh)
    response.headers["Cache-Control"] = "public, max-age=3600" if result.get("found") else "no-store"
    return result


@router.get("/search", response_model=SearchResponse)
async def search_address(
    response: Response,
    q: str = Query(..., min_length=1, max_length=200, description="Alamat/nama daerah"),
    limit: int = Query(5, ge=1, le=20),
    type: str = Query("all", pattern="^(all|region|place)$"),
    include_geometry: bool = Query(False, description="Sertakan polygon batas (payload besar)"),
) -> dict:
    """Autocomplete wilayah administratif dan POI/alamat OSM."""
    results, took_ms = await search.search_places(
        q, limit=limit, kind=type, include_geometry=include_geometry
    )
    response.headers["Cache-Control"] = "public, max-age=60"
    return {
        "query": q,
        "count": len(results),
        "results": results,
        "took_ms": took_ms,
    }


@router.get("/regions/hierarchy", response_model=HierarchyResponse)
async def hierarchy(
    response: Response,
    code: str | None = Query(None, pattern=r"^\d{2,13}$"),
    parent_code: str | None = Query(None, pattern=r"^\d{2,13}$"),
    level: int | None = Query(None, ge=1, le=4),
    depth: int = Query(1, ge=0, le=4),
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    include_geometry: bool = Query(False),
) -> dict:
    """Hierarki wilayah berjenjang (provinsi -> kab/kota -> kecamatan -> desa)."""
    data, meta = await regions.get_hierarchy(
        code=code,
        parent_code=parent_code,
        level=level,
        depth=depth,
        q=q,
        limit=limit,
        offset=offset,
        include_geometry=include_geometry,
    )
    response.headers["Cache-Control"] = "public, max-age=3600"
    return {"data": data, "meta": meta}


@router.get("/regions/{code}")
async def region_detail(
    code: str,
    include_geometry: bool = Query(False),
) -> dict:
    item = await regions.get_region(code, include_geometry=include_geometry)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Wilayah {code} tidak ditemukan")
    return item


@router.get("/regions/{code}/boundary")
async def region_boundary(
    code: str,
    simplify: float = Query(0.0005, ge=0, le=0.1, description="Toleransi ST_Simplify (derajat)"),
) -> dict:
    feature = await regions.get_boundary(code, simplify=simplify)
    if feature is None:
        raise HTTPException(
            status_code=404,
            detail=f"Polygon wilayah {code} tidak tersedia (data desa tertentu hanya centroid).",
        )
    return feature
