from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Coordinates(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class RegionRef(BaseModel):
    code: str
    name: str


class RegionChain(BaseModel):
    province: RegionRef | None = None
    regency: RegionRef | None = None
    district: RegionRef | None = None
    village: RegionRef | None = None


class AddressInfo(BaseModel):
    line1: str | None = None
    street: str | None = None
    housenumber: str | None = None
    village: str | None = None
    district: str | None = None
    regency: str | None = None
    province: str | None = None
    postcode: str | None = None
    formatted: str | None = None
    label: str | None = None


class NearestRoad(BaseModel):
    name: str
    ref: str | None = None
    highway: str | None = None
    distance_m: float | None = None


class NearestPlace(BaseModel):
    name: str
    category: str | None = None
    type: str | None = None
    lat: float | None = None
    lon: float | None = None
    distance_m: float | None = None


class Nearest(BaseModel):
    road: NearestRoad | None = None
    place: NearestPlace | None = None


class MatchInfo(BaseModel):
    method: Literal["polygon", "nearest", "none"] = "none"
    level: int | None = None
    approximate: bool = False
    distance_m: float | None = None
    confidence: float | None = None


class ReverseResponse(BaseModel):
    found: bool
    location: Coordinates
    region: RegionChain | None = None
    address: AddressInfo | None = None
    nearest: Nearest | None = None
    match: MatchInfo | None = None
    source: str | None = None
    cached: bool | None = None
    reason: str | None = None


class SearchItem(BaseModel):
    id: str
    kind: Literal["region", "place"]
    name: str
    label: str
    level: int | None = None
    lat: float
    lng: float
    bbox: list[float] | None = None
    postcode: str | None = None
    category: str | None = None
    type: str | None = None
    region: RegionChain | None = None
    score: float | None = None
    geometry: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    query: str
    count: int
    results: list[SearchItem]
    took_ms: float | None = None


class HierarchyNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    name: str
    level: int
    parent_code: str | None = None
    full_name: str | None = None
    postal_codes: list[str] = Field(default_factory=list)
    centroid: Coordinates | None = None
    bbox: list[float] | None = None
    children: list[HierarchyNode] = Field(default_factory=list)


class HierarchyResponse(BaseModel):
    data: list[HierarchyNode]
    meta: dict[str, Any] = Field(default_factory=dict)


HierarchyNode.model_rebuild()
