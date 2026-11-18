"""Vexcel API 2.0: footprints, obliques, ortho. WKT is POINT(lon lat), srid 4326.

Every response is cached under cache/vexcel/ keyed by the request, so a demo can
run offline once warmed up. 429s back off 1, 2, 4, 8, 16 s (+ jitter).

Notes from probing (Nov 14):
- property/extract returns one feature per parcel *per collection* (survey year),
  even with latest=true. building_outlines() keeps the newest footprint and drops
  older ones that overlap it.
- Structures have no id. building_id = "vx_" + hash of the chosen footprint WKT,
  stable as long as the cached response is the same.
- include=footprint-wkt,building-type is rejected; the default include already
  has footprint.wkt, building-type.class, ground-elevation and roof fields.
- "oblique-north" = camera looking north, so it shows south-facing facades.
"""
from __future__ import annotations

import hashlib
import json
import os
import math

from ._common import cache_key, cache_path, cached_json, request_with_backoff, require_env, use_stubs

API = "https://api.vexcelgroup.com/v2"
ALL_LAYERS = "urban,urban-r,wide-area,urban-g"
PAGE_SIZE = 500
DIRECTIONS = {"oblique-north": 0, "oblique-east": 90, "oblique-south": 180, "oblique-west": 270}


class VexcelError(RuntimeError):
    pass


def _headers() -> dict:
    return {"X-API-KEY": require_env("VEXCEL_API_KEY")}


def _get_json(path: str, params: dict, allow_404: bool = True):
    def fetch():
        r = request_with_backoff("GET", f"{API}/{path}", headers=_headers(), params=params, timeout=180)
        if r.status_code == 404 and allow_404:
            return {"type": "FeatureCollection", "features": [], "_status": 404}
        if not r.ok:
            raise VexcelError(f"GET {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()
    return cached_json("vexcel", ["GET", path, params], fetch)


def _post_image(path: str, body: dict, ext: str = "jpg"):
    """POST an extract request; cache and return the image path (or None on 404)."""
    p = cache_path("vexcel_img", cache_key("POST", path, body), ext)
    miss = p.with_suffix(".404")
    if p.exists() and p.stat().st_size > 0:
        return str(p)
    if miss.exists():
        return None
    r = request_with_backoff("POST", f"{API}/{path}", headers=_headers(), json=body, timeout=180)
    if r.status_code == 404:
        miss.write_text(r.text[:500])
        return None
    if not r.ok or not r.headers.get("content-type", "").startswith("image"):
        raise VexcelError(f"POST {path} -> {r.status_code}: {r.text[:300]}")
    p.write_bytes(r.content)
    return str(p)


# --- geometry helpers ------------------------------------------------------------

def _m_per_deg(lat: float) -> tuple[float, float]:
    return 111_320.0, 111_320.0 * math.cos(math.radians(lat))


def square_wkt(lat: float, lon: float, half_m: float) -> str:
    my, mx = _m_per_deg(lat)
    dlat, dlon = half_m / my, half_m / mx
    pts = [(lon - dlon, lat - dlat), (lon + dlon, lat - dlat), (lon + dlon, lat + dlat),
           (lon - dlon, lat + dlat), (lon - dlon, lat - dlat)]
    return "POLYGON((" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in pts) + "))"


def _features_in_square(lat: float, lon: float, half_m: float, depth: int = 0) -> list[dict]:
    d = _get_json("property/extract", {
        "wkt": square_wkt(lat, lon, half_m), "srid": 4326, "layer": ALL_LAYERS,
        "latest": "true", "unit-system": "metric", "page-size": PAGE_SIZE})
    feats = d.get("features", [])
    if len(feats) < PAGE_SIZE or depth >= 3:
        return feats
    # page full: split into four quadrants so nothing is silently dropped
    my, mx = _m_per_deg(lat)
    q = half_m / 2
    out = []
    for sy in (-1, 1):
        for sx in (-1, 1):
            out += _features_in_square(lat + sy * q / my, lon + sx * q / mx, q, depth + 1)
    return out


def _collection_rank(props: dict) -> tuple:
    return (props.get("metadata.ortho-date-estimate") or "", props.get("metadata.collection") or "")


def building_details(lat: float, lon: float, radius_m: float) -> list[dict]:
    """Deduplicated structures near a point, newest collection first, with extra fields.

    Keys: building_id, outline (WKT), height_m, building_type, ground_elevation_m,
    primary (bool), collection, distance_m (from the point to the footprint, 0 if inside).
    """
    from shapely import wkt as swkt
    from shapely.geometry import Point

    feats = _features_in_square(lat, lon, radius_m)
    feats.sort(key=lambda f: _collection_rank(f.get("properties", {})), reverse=True)
    my, mx = _m_per_deg(lat)
    here = Point(lon, lat)
    kept: list[tuple] = []
    for f in feats:
        props = f.get("properties", {})
        for s in props.get("structures", []):
            w = s.get("footprint.wkt")
            if not w:
                continue
            shp = swkt.loads(w)
            if not shp.is_valid:
                shp = shp.buffer(0)
            if any(_overlaps(shp, k) for k, _ in kept):
                continue
            dist_deg = shp.distance(here)
            # convert degree distance to metres using the nearest point
            if dist_deg == 0:
                dist_m = 0.0
            else:
                from shapely.ops import nearest_points
                np_ = nearest_points(shp, here)[0]
                dist_m = math.hypot((np_.x - lon) * mx, (np_.y - lat) * my)
            if dist_m > radius_m:
                continue
            kept.append((shp, {
                "building_id": "vx_" + hashlib.sha1(w.encode()).hexdigest()[:10],
                "outline": w,
                "height_m": s.get("roof-characteristics.maximum-roof-height"),
                "building_type": s.get("building-type.class"),
                "ground_elevation_m": s.get("ground-elevation.value"),
                "primary": bool(s.get("primary-structure")),
                "collection": props.get("metadata.collection"),
                "distance_m": round(dist_m, 2),
            }))
    rows = [r for _, r in kept]
    rows.sort(key=lambda r: (r["distance_m"], r["building_id"]))
    return rows


def _overlaps(a, b) -> bool:
    inter = a.intersection(b).area
    if inter == 0:
        return False
    return inter / min(a.area, b.area) > 0.3


def building_outlines(lat: float, lon: float, radius_m: float) -> list[dict]:
    """Building footprints near a point, nearest first.

    Returns dicts with keys: outline (WKT, lon lat), height_m (None if not fetched), building_id.
    """
    if use_stubs():
        return []  # Avishek's stub
    return [{"outline": r["outline"], "height_m": r["height_m"], "building_id": r["building_id"]}
            for r in building_details(lat, lon, radius_m)]


def roof_height(lat: float, lon: float) -> dict:
    """Computed roof/eave heights for the parcel at a point (slow; cached). Metric."""
    d = _get_json("property/extract", {
        "wkt": f"POINT({lon} {lat})", "srid": 4326, "layer": ALL_LAYERS, "latest": "true",
        "include": "calculated", "unit-system": "metric"})
    return d


# --- obliques ----------------------------------------------------------------------

def oblique_directions(area_wkt: str) -> list[str]:
    """Oblique product types available over an area in its newest collection."""
    d = _get_json("oriented/collections", {
        "wkt": area_wkt, "srid": 4326, "layer": "urban", "product-type": "oblique",
        "include": "product-type,collection,last-capture-date"})
    feats = d.get("features", [])
    newest = max((f["properties"].get("last-capture-date") or "" for f in feats), default=None)
    avail = {f["properties"].get("product-type") for f in feats
             if (f["properties"].get("last-capture-date") or "") == newest}
    return [k for k in DIRECTIONS if k in avail]


def camera_direction_for(heading_deg: float) -> str:
    """Oblique product whose camera looks back at a facade facing heading_deg."""
    cam = (heading_deg + 180) % 360
    return min(DIRECTIONS, key=lambda k: _angdiff(DIRECTIONS[k], cam))


def _angdiff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _area_for_point(lat: float, lon: float) -> str:
    """Footprint of the building at the point, else an 30 m square around it."""
    try:
        b = building_details(lat, lon, 25)
    except VexcelError:
        b = []
    inside = [r for r in b if r["distance_m"] == 0]
    return (inside or [{"outline": None}])[0]["outline"] or square_wkt(lat, lon, 30)


def oblique_view(lat: float, lon: float, heading_deg: float) -> str:
    """Path to an oblique image of the facade facing heading_deg (camera = heading + 180).

    heading_deg is a true-north bearing of the facade's outward direction (the way a
    window looks out). If that camera direction is missing here, the nearest available
    direction is used; a sidecar <image>.json records what was used.
    """
    if use_stubs():  # Avishek's stub: a path, no file
        return f"data/vexcel/oblique_{lat:.4f}_{lon:.4f}_{int(heading_deg) % 360}.jpg"
    area = _area_for_point(lat, lon)
    available = oblique_directions(area)
    if not available:
        raise VexcelError(f"no oblique coverage at ({lat}, {lon}) (only the 'urban' layer has obliques)")
    want = camera_direction_for(heading_deg)
    cam = (heading_deg + 180) % 360
    used = want if want in available else min(available, key=lambda k: _angdiff(DIRECTIONS[k], cam))
    body = {
        "wkt": area, "srid": 4326, "layer": "urban", "product-type": used,
        # no outline drawing: a ground footprint drawn on an oblique zigzags up the
        # facade and gets in the way of the window comparison
        "rotation": "natural", "buffer-meter": 15, "crop": "bbox", "image-format": "jpeg",
    }
    path = _post_image("oriented/extract", body)
    if path is None:
        raise VexcelError(f"oriented/extract 404 for {used} at ({lat}, {lon})")
    sidecar = path.rsplit(".", 1)[0] + ".json"
    if os.environ.get("DOME_OFFLINE") == "1" and os.path.exists(sidecar):
        return path                                      # the offline bundle is read-only; keep the recorded sidecar
    with open(sidecar, "w") as f:
        json.dump({"lat": lat, "lon": lon, "heading_deg": heading_deg, "wanted": want,
                   "used": used, "available": available, "area_wkt": area}, f)
    return path


def ortho_view(area_wkt: str, size_px: int = 1024, buffer_m: float = 20,
               drawings: list[dict] | None = None) -> str:
    """Top-down image of an area (path). drawings: Vexcel drawing dicts (e.g. outlines)."""
    body = {"wkt": area_wkt, "srid": 4326, "layer": ALL_LAYERS, "buffer-meter": buffer_m,
            "crop": "bounding_box", "image-format": "jpeg",
            "destination-dimensions": f"{size_px},{size_px}"}
    if drawings:
        body["drawing"] = drawings
    path = _post_image("ortho/extract", body)
    if path is None:
        raise VexcelError("ortho/extract 404")
    return path


# --- window detection on obliques, georeferenced ortho (hand-check kit, geo) -------

def _post_json_cached(path: str, body: dict) -> dict:
    """POST returning JSON, cached. Errors are cached too (as {"_error": ...}) so a
    re-run costs nothing; delete the cache file to retry."""
    def fetch():
        r = request_with_backoff("POST", f"{API}/{path}", headers=_headers(), json=body, timeout=300)
        if not r.ok:
            return {"_error": f"{r.status_code}: {r.text[:200]}"}
        return r.json()
    return cached_json("vexcel", ["POST", path, body], fetch)


def oblique_image(area_wkt: str, direction: str) -> str | None:
    """Clean oblique crop of an area (no drawings). Same request detect_oblique_windows uses."""
    req = {"layer": "urban", "srid": 4326, "wkt": area_wkt, "product-type": direction,
           "rotation": "natural", "crop": "bbox"}
    return _post_image("oriented/extract", {**req, "image-format": "jpeg"})


def detect_oblique_windows(area_wkt: str, direction: str, threshold: float = 0.4) -> dict:
    """elements/detect "window" (sam3) on one oblique of an area.

    Returns {image, width, height, boxes: [{x, y, w, h, confidence}], metadata, error}.
    Boxes are pixel boxes in `image`. Vexcel 500s on large areas (a 100 m square works;
    a big footprint polygon did not), so pass a square around the building.
    """
    req = {"layer": "urban", "srid": 4326, "wkt": area_wkt, "product-type": direction,
           "rotation": "natural", "crop": "bbox"}
    out = {"image": None, "width": None, "height": None, "boxes": [], "metadata": {}, "error": None}
    try:
        out["image"] = oblique_image(area_wkt, direction)
    except VexcelError as e:
        out["error"] = str(e)
        return out
    if out["image"] is None:
        out["error"] = "no oblique image for this direction (404)"
        return out
    body = {"wkt": area_wkt, "srid": 4326, "buffer-meter": 0,
            "images": [{"endpoint": "oriented/extract", "request": req}],
            "model-input": {"elements": [{"label": "window", "model": "sam3",
                                          "detection-threshold": threshold}],
                            "include": ["bbox", "confidence", "pixel-bbox"]}}
    d = _post_json_cached("elements/detect", body)
    if "_error" in d:
        out["error"] = "elements/detect " + d["_error"]
        return out
    meta = (d.get("images") or [{}])[0].get("metadata", {})
    out["metadata"] = {k: meta.get(k) for k in ("collection", "capture-date", "product-type",
                                                "camera-pos-x", "camera-pos-y", "camera-pos-z",
                                                "ground-z", "omega", "phi", "kappa", "utm-zone",
                                                "focal-length", "pixel-size", "pp0-x", "pp0-y", "pixel-bbox",
                                                "raster-size-width", "raster-size-height",
                                                "width", "height", "min-gsd", "max-gsd")}
    from PIL import Image
    with Image.open(out["image"]) as im:
        out["width"], out["height"] = im.size
    sx = out["width"] / meta["width"] if meta.get("width") else 1.0
    sy = out["height"] / meta["height"] if meta.get("height") else 1.0
    for f in d.get("features", []):
        for det in (f.get("properties") or {}).get("detections", []):
            x, y, w, h = det["pixel-bbox"]
            out["boxes"].append({"x": round(x * sx, 1), "y": round(y * sy, 1),
                                 "w": round(w * sx, 1), "h": round(h * sy, 1),
                                 "confidence": round(det.get("confidence", 0), 3),
                                 "ground_wkt": det.get("bbox")})
    return out


def ortho_square(lat: float, lon: float, half_m: float) -> tuple[str, tuple[float, float, float, float]]:
    """Top-down image of a square around a point. Returns (path, (min_lon, min_lat, max_lon, max_lat)).

    The image covers exactly the square (crop to bounding box, no buffer), so lon/lat
    map linearly to pixels for drawing overlays locally.
    """
    area = square_wkt(lat, lon, half_m)
    body = {"wkt": area, "srid": 4326, "layer": ALL_LAYERS, "buffer-meter": 0,
            "crop": "bounding_box", "image-format": "jpeg"}
    path = _post_image("ortho/extract", body)
    if path is None:
        raise VexcelError("ortho/extract 404")
    my, mx = _m_per_deg(lat)
    return path, (lon - half_m / mx, lat - half_m / my, lon + half_m / mx, lat + half_m / my)
