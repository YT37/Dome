"""CoStar kit (local JSONL download) -> candidate properties.

The kit is a password-protected local download, not an API. On first use we stream
the JSONL files line by line and build a small SQLite index at
cache/costar_index.sqlite (one row per property, plus one row per Matterport model).

How properties link to scans: the kit's starter CSVs (commercial-properties.csv,
residential-listings.csv) list every Matterport model id for each property or
listing. That is CoStar's own link, so no address matching is needed.

property_id prefixes: "CS-<PropertyId>" for commercial properties,
"RL-<ListingId>" for residential MLS listings (homes, condos, townhouses).
scan_id is the first model listed in the CSV for that key; scans_for_property()
returns all of them.

Type strings (lowercase): commercial "multifamily", "hotel", "office", "retail",
"industrial", "flex", "land", "mixed_use", "specialty", "healthcare",
"sports_entertainment", "residential", "homes", "unknown"; residential listings
"residential_detached", "residential_condo", "residential_townhouse", ...
`type` is CoStar's raw word (Avishek's decision, Nov 14): the Lister maps it with
config.COSTAR_TYPE_MAP (hotel -> hospitality, houses/townhouses -> single_family, condos
-> multifamily). A filter value matches the raw type or its prefix before "_"
("residential" = all residential_*). `types=[]` means all types.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from pathlib import Path

from . import _stub
from ._common import REPO_ROOT, cache_dir, load_env, use_stubs

INDEX_VERSION = 1

COMMERCIAL_TYPES = {
    0: "unknown", 1: "hotel", 2: "industrial", 3: "land", 5: "office", 6: "retail",
    7: "flex", 8: "sports_entertainment", 9: "mixed_use", 10: "specialty",
    11: "multifamily", 13: "healthcare", 14: "unknown", 15: "residential", 16: "homes",
}
RESIDENTIAL_TYPES = {
    1: "detached", 2: "townhouse", 4: "condo", 8: "other", 16: "multifamily",
    32: "land", 64: "mobile", 128: "commercial", 256: "coop", 512: "duplex",
    1024: "triplex", 2048: "quadruplex",
}
CONSTRUCTION_COMPLETE = 2



def kit_dir() -> Path:
    load_env()
    d = Path(os.environ.get("COSTAR_KIT_DIR", REPO_ROOT / "costar_kit"))
    if not d.is_absolute():
        d = REPO_ROOT / d
    if not (d / "data" / "commercial-property.jsonl").exists():
        raise RuntimeError(
            f"CoStar kit not found at {d}. Unzip costar-hackathon-kit.zip there "
            "(password from #costar-group) or set COSTAR_KIT_DIR."
        )
    return d


def _index_path() -> Path:
    return cache_dir() / f"costar_index_v{INDEX_VERSION}.sqlite"


def _iter_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def _read_csv_models(path: Path, key_col: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mid = (row.get("MatterportModelId") or "").strip()
            lst = out.setdefault(row[key_col].strip(), [])
            if mid and mid not in lst:
                lst.append(mid)
    return out


def _commercial_row(r: dict, models: dict[str, list[str]]):
    addr = r.get("primaryAddress") or {}
    lat, lon = addr.get("latitude"), addr.get("longitude")
    if lat is None or lon is None:
        return None
    ptype = COMMERCIAL_TYPES.get(r.get("propertyType") or 0, "unknown")
    events = r.get("constructionEvents") or []
    built = [e["year"] for e in events if e.get("eventType") == CONSTRUCTION_COMPLETE and e.get("year")]
    units = None
    if r.get("propertyApartment"):
        units = r["propertyApartment"].get("totalNumUnits")
    if units is None and r.get("propertyHospitality"):
        units = r["propertyHospitality"].get("numUnits")
    street = " ".join(str(addr.get(k) or "") for k in ("streetNumber", "streetName", "streetType")).split()
    address = ", ".join(x for x in (" ".join(street), addr.get("city"), addr.get("state")) if x)
    pid = str(r["id"])
    return {
        "property_id": f"CS-{pid}", "address": address, "lat": float(lat), "lon": float(lon),
        "type": ptype, "floors": r.get("numStoriesAboveGrade"), "units": units,
        "year_built": min(built) if built else None, "name": r.get("buildingName"),
        "scan_ids": models.get(pid, []),
    }


def _residential_row(r: dict, models: dict[str, list[str]]):
    prop = r.get("property") or {}
    addr = prop.get("address") or {}
    lat, lon = addr.get("latitude"), addr.get("longitude")
    if lat is None or lon is None:
        return None
    rt = prop.get("propertyType") or prop.get("listingPropertyType") or 8
    structure = ((r.get("resoValues") or {}).get("structure")) or {}
    full = addr.get("fullStreetAddress") or ""
    unit = addr.get("unitNumber")
    if unit and unit not in full:
        full = f"{full} Unit {unit}"
    lid = str(r["id"])
    return {
        "property_id": f"RL-{lid}",
        "address": ", ".join(x for x in (full, addr.get("city"), addr.get("state")) if x),
        "lat": float(lat), "lon": float(lon),
        "type": "residential_" + RESIDENTIAL_TYPES.get(rt, "other"),
        "floors": structure.get("storiesTotal") or structure.get("stories"),
        "units": None, "year_built": prop.get("yearBuilt"), "name": None,
        "scan_ids": models.get(lid, []),
    }


def build_index(force: bool = False) -> Path:
    """Stream the kit's JSONL files into a SQLite index. Idempotent; cached."""
    path = _index_path()
    if path.exists() and not force:
        return path
    kit = kit_dir()
    com_models = _read_csv_models(kit / "commercial-properties.csv", "PropertyId")
    res_models = _read_csv_models(kit / "residential-listings.csv", "ListingId")

    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript("""
        CREATE TABLE properties (
            property_id TEXT PRIMARY KEY, address TEXT, lat REAL, lon REAL, type TEXT,
            floors INTEGER, units INTEGER, year_built INTEGER, name TEXT);
        CREATE TABLE scans (property_id TEXT, scan_id TEXT, rank INTEGER,
                            PRIMARY KEY (property_id, scan_id));
    """)

    def insert(row):
        if row is None:
            return
        scan_ids = row.pop("scan_ids")
        con.execute("INSERT OR REPLACE INTO properties VALUES (?,?,?,?,?,?,?,?,?)",
                    tuple(row[k] for k in ("property_id", "address", "lat", "lon", "type",
                                           "floors", "units", "year_built", "name")))
        con.executemany("INSERT OR IGNORE INTO scans VALUES (?,?,?)",
                        [(row["property_id"], s, i) for i, s in enumerate(scan_ids)])

    for r in _iter_jsonl(kit / "data" / "commercial-property.jsonl"):
        insert(_commercial_row(r, com_models))
    for r in _iter_jsonl(kit / "data" / "residential-listings.jsonl"):
        insert(_residential_row(r, res_models))

    con.executescript("""
        CREATE INDEX idx_latlon ON properties (lat, lon);
        CREATE INDEX idx_scan ON scans (scan_id);
    """)
    con.commit()
    con.close()
    tmp.replace(path)
    return path


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(build_index())
    con.row_factory = sqlite3.Row
    return con


def _type_matches(ptype: str, wanted: set[str]) -> bool:
    return ptype in wanted or any(ptype.startswith(w + "_") for w in wanted)


def _first_scans(con, ids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = (f"SELECT property_id, scan_id FROM scans WHERE property_id IN "
             f"({','.join('?' * len(chunk))}) ORDER BY property_id, rank")
        for pid, sid in con.execute(q, chunk):
            out.setdefault(pid, sid)
    return out


def properties_in_polygon(polygon: list[tuple[float, float]], types: list[str]) -> list[dict]:
    """Properties inside polygon, filtered by type.

    polygon: list of (lat, lon) points. types: e.g. ["multifamily", "hotel"]; empty = all.
    Returns dicts with keys: property_id, address, lat, lon, type, floors, units,
    year_built, has_scan, scan_id. Sorted by property_id for determinism.
    """
    if use_stubs():
        return _stub_properties_in_polygon(polygon, types)
    from shapely.geometry import Point, Polygon
    from shapely.prepared import prep

    if len(polygon) < 3:
        return []
    poly = Polygon([(lon, lat) for lat, lon in polygon])  # shapely x=lon, y=lat
    if not poly.is_valid:
        poly = poly.buffer(0)
    shape = prep(poly)
    min_lon, min_lat, max_lon, max_lat = poly.bounds
    wanted = {t.strip().lower() for t in types if t and t.strip()}

    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM properties WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? "
            "ORDER BY property_id", (min_lat, max_lat, min_lon, max_lon)).fetchall()
        rows = [r for r in rows
                if (not wanted or _type_matches(r["type"], wanted))
                and shape.covers(Point(r["lon"], r["lat"]))]
        first = _first_scans(con, [r["property_id"] for r in rows])

    return [{
        "property_id": r["property_id"], "address": r["address"], "lat": r["lat"],
        "lon": r["lon"], "type": r["type"], "floors": r["floors"], "units": r["units"],
        "year_built": r["year_built"], "has_scan": r["property_id"] in first,
        "scan_id": first.get(r["property_id"]),
    } for r in rows]


# --- helpers beyond the contract (safe for other modules to use) ---------------

def scans_for_property(property_id: str) -> list[str]:
    """Every Matterport model id CoStar lists for a property, in CSV order."""
    with _connect() as con:
        return [s for (s,) in con.execute(
            "SELECT scan_id FROM scans WHERE property_id = ? ORDER BY rank", (property_id,))]


def property_for_scan(scan_id: str) -> dict | None:
    """The CoStar property (or listing) a Matterport model belongs to, or None."""
    with _connect() as con:
        r = con.execute(
            "SELECT p.* FROM scans s JOIN properties p USING (property_id) WHERE s.scan_id = ? "
            "ORDER BY p.property_id LIMIT 1", (scan_id,)).fetchone()
        return dict(r) if r else None


def _floor_from_unit(unit_number: str | None, floor_number: str | None, building_floors: int | None) -> int | None:
    """Floor of an apartment unit: floorNumber if numeric, else from the unit number
    (5004 -> 5 in a 7-story building, 1204 -> 12 in a 20-story one)."""
    if floor_number and str(floor_number).strip().isdigit():
        return int(str(floor_number).strip())
    digits = "".join(ch for ch in str(unit_number or "") if ch.isdigit())
    if len(digits) < 3:
        return None
    cands = [int(digits[:-2]), int(digits[:-3]) if len(digits) >= 4 else None]
    for c in cands:
        if c and 1 <= c <= (building_floors or 200):
            return c
    return None


def unit_floors_for_scan(scan_id: str) -> dict:
    """Floors CoStar ties to a scan through apartment units.

    A scan attached to a floor plan (model) covers every unit of that plan; a scan attached
    to one unit gives one floor. Returns {"floors": sorted list, "units": [...], "level":
    "unit" | "model" | None, "building_floors": int | None}.
    """
    p = property_for_scan(scan_id)
    out = {"floors": [], "units": [], "level": None, "building_floors": (p or {}).get("floors")}
    if p and p["property_id"].startswith("RL-"):
        # a residential listing is one home: its address carries the unit ("..., Unit 307")
        import re
        m = re.search(r"\b(?:unit|apt|#)\s*([A-Za-z]?\d+[A-Za-z]?)\b", p.get("address") or "", re.I)
        if m:
            f = _floor_from_unit(m.group(1), None, p.get("floors"))
            out.update(level="listing", units=[[m.group(1), None]], floors=[f] if f else [])
        return out
    if not p or not p["property_id"].startswith("CS-"):
        return out
    pid = int(p["property_id"][3:])

    def fetch():
        with open(kit_dir() / "data" / "commercial-property.jsonl", encoding="utf-8") as f:
            for line in f:
                if f'"id": {pid},' not in line and f'"id":{pid},' not in line:
                    continue
                r = json.loads(line)
                if r.get("id") != pid:
                    continue
                for m in (r.get("propertyApartment") or {}).get("models") or []:
                    units = m.get("units") or []
                    for u in units:
                        if any(a.get("videoKey") == scan_id for a in u.get("attachments") or []):
                            return {"level": "unit", "units": [[u.get("unitNumber"), u.get("floorNumber")]]}
                    if any(a.get("videoKey") == scan_id for a in m.get("attachments") or []):
                        return {"level": "model", "units": [[u.get("unitNumber"), u.get("floorNumber")] for u in units]}
        return {"level": None, "units": []}
    from ._common import cached_json
    got = cached_json("costar", ["unit_floors", scan_id, INDEX_VERSION], fetch)
    floors = {_floor_from_unit(u, f, out["building_floors"]) for u, f in got["units"]}
    out.update(level=got["level"], units=got["units"], floors=sorted(x for x in floors if x))
    return out


# --- Avishek's stub (answers from samples/scenarios/<DOME_SCENARIO>/scenario.json) ---------

def _inside(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon; polygon is [lat, lon] pairs."""
    inside = False
    n = len(polygon)
    for i in range(n):
        (y1, x1), (y2, x2) = polygon[i], polygon[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _stub_properties_in_polygon(polygon, types):
    out = []
    for b in _stub.scenario()["buildings"]:
        if _inside(b["lat"], b["lon"], polygon) and (not types or b["type"] in types):
            out.append(dict(b))
    return sorted(out, key=lambda b: b["property_id"])


def unit_scans() -> dict[str, dict]:
    """Every scan CoStar ties to one apartment unit: scan_id -> {property_id, unit, floor_text}.
    One pass over the kit, cached."""
    from ._common import cached_json

    def fetch():
        out = {}
        with open(kit_dir() / "data" / "commercial-property.jsonl", encoding="utf-8") as f:
            for line in f:
                if '"units"' not in line or "videoKey" not in line:
                    continue
                r = json.loads(line)
                for m in (r.get("propertyApartment") or {}).get("models") or []:
                    for u in m.get("units") or []:
                        for a in u.get("attachments") or []:
                            if a.get("videoKey"):
                                out.setdefault(a["videoKey"], {"property_id": f"CS-{r['id']}",
                                                               "unit": u.get("unitNumber"),
                                                               "floor_text": u.get("floorNumber")})
        return out
    return cached_json("costar", ["unit_scans", INDEX_VERSION], fetch)
