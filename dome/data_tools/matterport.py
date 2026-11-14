"""Matterport Model API (GraphQL). Read-only: never call any mutation.

Auth: HTTP Basic, username = MATTERPORT_TOKEN_ID (the "API key"), password =
MATTERPORT_TOKEN_SECRET (the "API token"). The token is admin-level: server-side only.

Skybox faces (from viewing them): children[0] = up, [1..4] = the four side faces,
going clockwise seen from above, [5] = down. Each side face is a 90-degree
perspective view, 2048x2048 at resolution "2k".

Heading convention used everywhere in data_tools: heading_deg is measured
clockwise from the model's +Y axis, looking down from +Z (model frame is z-up).
A side face's heading = SKYBOX_YAW_SIGN * pano_yaw + 90 * (k - 1) + SKYBOX_OFFSET_DEG,
where pano_yaw comes from the pano rotation quaternion. The sign and offset were
fitted from relative camera pose between sweeps; see scripts/calibrate_skybox.py.

Skybox URLs expire, so faces are downloaded right away and cached under
cache/matterport/<scan_id>/. If a cached URL has expired, the query is re-run.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import _stub
from ._common import cache_dir, cached_json, request_with_backoff, require_env, use_stubs

API = "https://api.matterport.com/api/models/graph"
SIDE_FACES = (1, 2, 3, 4)
# Fitted Nov 14 by scripts/calibrate_skybox.py on 5 scans (2 properties' worth of sweeps):
# sign -1, clockwise face order, offset 90 won with 820 and 449 epipolar inliers vs
# ~60 / ~33 for other offsets. So side face 2 looks along heading = -pano_yaw.
SKYBOX_YAW_SIGN = -1
SKYBOX_OFFSET_DEG = 90.0


class MatterportError(RuntimeError):
    pass


def graphql(query: str, variables: dict | None = None) -> dict:
    """Run a read-only GraphQL query. Refuses anything that looks like a mutation."""
    if query.lstrip().lower().startswith("mutation"):
        raise MatterportError("mutations are not allowed from data_tools")
    auth = (require_env("MATTERPORT_TOKEN_ID"), require_env("MATTERPORT_TOKEN_SECRET"))
    r = request_with_backoff("POST", API, auth=auth,
                             json={"query": query, "variables": variables or {}}, timeout=90)
    if not r.ok:
        raise MatterportError(f"GraphQL HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    if body.get("errors") and not body.get("data"):
        raise MatterportError(f"GraphQL errors: {json.dumps(body['errors'])[:300]}")
    return body


Q_LIST = "query l($q: String, $offset: String) { models(query: $q, offset: $offset) { totalResults nextOffset results { id name created } } }"
Q_DETAILS = """query d($id: ID!) { model(id: $id) { id name created
  publication { address published url }
  floors { id label sequence }
  rooms { id label tags dimensions { areaFloor width depth height units } floor { id } } } }"""
Q_GEO = """query g($id: ID!) { model(id: $id) { geocoordinates {
  source latitude longitude altitude translation { x y z } rotation { x y z w } } } }"""
Q_PANOS = """query p($id: ID!) { model(id: $id) { locations {
  id position { x y z } floor { id } room { id }
  panos { id position { x y z } rotation { x y z w } skybox(resolution: "2k") { status format children } } } } }"""
Q_FLOORPLANS = """query f($id: ID!) { model(id: $id) { assets {
  floorplans(provider: "matterport", flags: [photogramy]) {
    floor { id label sequence } format url origin { x y } width height resolution } } } }"""


def model_details(scan_id: str) -> dict:
    """Name, publication address, floors and rooms (cached)."""
    return cached_json("matterport", ["details", scan_id],
                       lambda: graphql(Q_DETAILS, {"id": scan_id}).get("data", {}).get("model") or {})


def geocoordinates(scan_id: str) -> dict | None:
    """Matterport's own geocoordinates for a model, or None if refused/missing (cached)."""
    def fetch():
        try:
            m = graphql(Q_GEO, {"id": scan_id}).get("data", {}).get("model") or {}
        except MatterportError:
            return {"geocoordinates": None}
        return {"geocoordinates": m.get("geocoordinates")}
    return cached_json("matterport", ["geo", scan_id], fetch)["geocoordinates"]


def _panos(scan_id: str, refresh: bool = False) -> list[dict]:
    key = ["panos", scan_id]
    if refresh:
        from ._common import cache_key, cache_path
        cache_path("matterport", cache_key(key), "json").unlink(missing_ok=True)
    data = cached_json("matterport", key,
                       lambda: graphql(Q_PANOS, {"id": scan_id}).get("data", {}).get("model") or {})
    return data.get("locations") or []


def quat_yaw_deg(q: dict) -> float:
    """Rotation about +Z (counter-clockwise, degrees) of a z-up quaternion."""
    x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    return math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))


def face_heading(pano_rotation: dict, face_index: int) -> float:
    """Model-frame heading (clockwise from +Y) of side face 1..4 of a pano."""
    yaw = quat_yaw_deg(pano_rotation)
    h = SKYBOX_YAW_SIGN * yaw + 90 * (face_index - 1) + SKYBOX_OFFSET_DEG
    return round(h % 360, 2)


def _download(url: str, dest: Path) -> bool:
    import requests
    r = requests.get(url, timeout=90)
    if r.status_code != 200 or not r.content:
        return False
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(r.content)
    tmp.replace(dest)
    return True


def face_paths(scan_id: str, faces=SIDE_FACES, _retried: bool = False) -> list[dict]:
    """Download (or reuse cached) skybox faces for every sweep.

    Returns one dict per (sweep, face): sweep_id, face, path, position, rotation, floor_id, room_id.
    """
    root = cache_dir() / "matterport" / scan_id
    root.mkdir(parents=True, exist_ok=True)
    out = []
    for loc in _panos(scan_id, refresh=_retried):
        pano = next((p for p in loc.get("panos") or []
                     if (p.get("skybox") or {}).get("status") == "available"
                     and len((p.get("skybox") or {}).get("children") or []) >= 6), None)
        if pano is None:
            continue
        urls = pano["skybox"]["children"]
        for k in faces:
            dest = root / f"{loc['id']}_f{k}.jpg"
            if not dest.exists() and not _download(urls[k], dest):
                if not _retried:  # cached URLs expired: re-query once, start over
                    return face_paths(scan_id, faces, _retried=True)
                continue
            out.append({"sweep_id": loc["id"], "face": k, "path": str(dest),
                        "position": loc.get("position"), "rotation": pano["rotation"],
                        "floor_id": (loc.get("floor") or {}).get("id"),
                        "room_id": (loc.get("room") or {}).get("id")})
    return out


def floor_index(scan_id: str) -> dict[str, int]:
    """Matterport floor id -> 0-based floor number (by sequence, then label order)."""
    floors = model_details(scan_id).get("floors") or []
    floors = sorted(floors, key=lambda f: (f.get("sequence") if f.get("sequence") is not None else 1e9,
                                           f.get("label") or "", f["id"]))
    return {f["id"]: i for i, f in enumerate(floors)}


def sweep_views(scan_id: str) -> list[dict]:
    """Perspective views for every sweep of a scan (four side cube faces per sweep).

    Returns dicts with keys: view_id, image_path, heading_deg (model frame, clockwise
    from +Y), floor (0-based), sweep_id. view_id = "<scan_id>/<sweep_id>/az_<000|090|180|270>",
    where az is the face's offset within the pano.
    """
    if use_stubs():  # Avishek's stub
        return [dict(v) for v in _stub.scenario().get("sweep_views", {}).get(scan_id, [])]
    floors = floor_index(scan_id)
    views = []
    for f in face_paths(scan_id):
        az = 90 * (f["face"] - 1)
        views.append({
            "view_id": f"{scan_id}/{f['sweep_id']}/az_{az:03d}",
            "image_path": f["path"],
            "heading_deg": face_heading(f["rotation"], f["face"]),
            "floor": floors.get(f["floor_id"], 0),
            "sweep_id": f["sweep_id"],
        })
    views.sort(key=lambda v: v["view_id"])
    return views


def floorplans(scan_id: str, refresh: bool = False) -> list[dict]:
    """Floor plan image metadata (url, origin in metres, resolution). URLs expire:
    pass refresh=True to re-query when a download returns 403/410."""
    if refresh:
        from ._common import cache_key, cache_path
        cache_path("matterport", cache_key(["floorplans", scan_id]), "json").unlink(missing_ok=True)
    data = cached_json("matterport", ["floorplans", scan_id],
                       lambda: graphql(Q_FLOORPLANS, {"id": scan_id}).get("data", {}).get("model") or {})
    return ((data.get("assets") or {}).get("floorplans")) or []
