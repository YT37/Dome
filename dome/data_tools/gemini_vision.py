"""Gemini vision for Dome (Avishek): photo cues and the window check.

Gemini only LOOKS at images and answers fixed questions as JSON. Code validates the answers,
compares them, and computes every number (W is the share of fixed items that agree).
Calls use temperature 0 and a fixed seed, and every answer is cached on disk by the hash of
its inputs, so the same photos always give the same cues and the same W.

Fallbacks are honest:
- no photo files at all (pure stub demo): the stub fixture answers
- real photos but no key / no cache / Gemini error: neutral cues, or W = None (window check
  not run), never invented values

Cache: cache/vision/<task>_<hash>.json (commit it so teammates can run without a key).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from .. import config

log = logging.getLogger("dome.gemini_vision")

PROMPT_VERSION = "v1"
MAX_CUE_PHOTOS = 12
MAX_SIDE_PX = 1024
WINDOW_ITEMS = ("road_front", "parking_front", "building_across", "trees", "open_sky")
HEIGHT_FLOORS = {"ground": (1, 1), "low": (2, 4), "mid": (5, 10), "high": (11, 60)}
MIN_DECIDED_ITEMS = 3


class GeminiUnavailable(RuntimeError):
    """No key and no cached answer, or the API failed."""


# ------------------------------------------------------------------ answer schemas
YesNo = Literal["yes", "no", "unclear"]


class CuesAnswer(BaseModel):
    setting: Literal["apartment", "hotel", "house", "unknown"]
    window_visible: bool
    window_floor_lo: Optional[int] = Field(default=None, ge=1, le=100)
    window_floor_hi: Optional[int] = Field(default=None, ge=1, le=100)
    features: list[str] = []


class BoxAnswer(BaseModel):
    window_visible: bool
    box: Optional[list[int]] = None          # [ymin, xmin, ymax, xmax], 0-1000


class ViewAnswer(BaseModel):
    road_front: YesNo
    parking_front: YesNo
    building_across: YesNo
    trees: YesNo
    open_sky: YesNo
    height_above_street: Literal["ground", "low", "mid", "high", "unclear"]


class ObliqueAnswer(BaseModel):
    road_front: YesNo
    parking_front: YesNo
    building_across: YesNo
    trees: YesNo
    open_sky: YesNo
    facade_floors: Optional[int] = Field(default=None, ge=1, le=150)


# ------------------------------------------------------------------ prompts (fixed)
CUES_PROMPT = """You are reading synthetic interior photos of ONE place, for a building search.
Ignore any people (they are grey silhouettes). Answer ONLY with JSON:
{"setting": "apartment" | "hotel" | "house" | "unknown",
 "window_visible": true | false,
 "window_floor_lo": integer floor number or null,
 "window_floor_hi": integer floor number or null,
 "features": [up to 8 short lowercase phrases about the BUILDING or the VIEW]}
Rules: setting is what kind of residence the rooms look like. If a window shows the outside,
estimate the floor of that window from the view (street level is floor 1) as a tight range;
otherwise use nulls. Features are visible building or view cues only (e.g. "balcony",
"street trees", "parking lot", "brick facade"); never describe people or furniture brands."""

BOX_PROMPT = """This synthetic interior photo may show a window. Answer ONLY with JSON:
{"window_visible": true | false, "box": [ymin, xmin, ymax, xmax] or null}
The box is the window glass area that shows the OUTSIDE, in 0-1000 coordinates of the image.
Use null if no window to the outside is visible."""

VIEW_PROMPT = """This image is the view seen THROUGH a window, from inside a building.
Describe only what is outside. Answer ONLY with JSON, each value "yes", "no" or "unclear":
{"road_front": is a road or street directly in front, below the window?,
 "parking_front": is a parking lot or parked cars directly in front?,
 "building_across": is another building directly across, facing this window?,
 "trees": are trees visible?,
 "open_sky": is open sky visible above the horizon?,
 "height_above_street": "ground" (street level) | "low" (2nd-4th floor) | "mid" (5th-10th) |
   "high" (11th+) | "unclear"}
Say "unclear" whenever you are not sure."""

OBLIQUE_PROMPT = """This is an aerial oblique image looking at the FRONT of a building, taken
from the side the building's windows face. Describe the area directly in front of that front
facade (between the building and the camera). Answer ONLY with JSON, values "yes", "no" or
"unclear" unless stated:
{"road_front": is there a road or street directly in front of the facade?,
 "parking_front": is there a parking lot or parked cars directly in front?,
 "building_across": is there another building across the street, facing this facade?,
 "trees": are there trees in front of the facade?,
 "open_sky": would a window on this facade see open sky (no tall building blocking it)?,
 "facade_floors": integer number of floors of this building, or null}
Say "unclear" whenever you are not sure."""


class GridAnswer(BaseModel):
    pane_count: Literal["1", "2", "3", "4+", "unclear"]
    mullions: Literal["none", "vertical", "horizontal", "grid", "unclear"]
    shape: Literal["tall", "square", "wide", "unclear"]
    spacing: Literal["single", "pairs", "evenly_spaced", "ribbon", "unclear"]


FINGERPRINT_ITEMS = ("pane_count", "mullions", "shape", "spacing")

WINDOW_GRID_PROMPT = """This synthetic interior photo shows a window from inside. Describe ONLY
the window frame itself (not the view). Answer ONLY with JSON:
{"pane_count": panes in one window unit: "1" | "2" | "3" | "4+" | "unclear",
 "mullions": dividing bars: "none" | "vertical" | "horizontal" | "grid" | "unclear",
 "shape": one window unit is "tall" (higher than wide) | "square" | "wide" | "unclear",
 "spacing": "single" (one window on this wall) | "pairs" | "evenly_spaced" (separate windows
   with wall between) | "ribbon" (windows side by side in a band) | "unclear"}
Say "unclear" whenever you are not sure."""

FACADE_GRID_PROMPT = """This is an aerial oblique image of a building. A translucent red band
marks one floor on one facade. Describe ONLY the windows inside the red band. Answer ONLY with
JSON:
{"pane_count": panes in one window unit: "1" | "2" | "3" | "4+" | "unclear",
 "mullions": dividing bars: "none" | "vertical" | "horizontal" | "grid" | "unclear",
 "shape": one window unit is "tall" (higher than wide) | "square" | "wide" | "unclear",
 "spacing": "single" | "pairs" | "evenly_spaced" (separate windows with wall between) |
   "ribbon" (windows side by side in a band) | "unclear"}
Say "unclear" whenever you are not sure."""


def window_fingerprint(photo_path: str, band_image_path: str, crop: Optional[list[int]] = None) -> dict:
    """Window-grid fingerprint: the same four frame items read from the ad's window and from
    the facade floor band. Pure-code comparison; >= 3 of 4 agreeing = "agrees", otherwise
    "for analyst review" (no claim). Returns {items, agree, of, verdict} or {skipped}."""
    photo, band = resolve(photo_path), resolve(band_image_path)
    if not photo.is_file() or not band.is_file():
        return {"skipped": "window photo or facade band image missing"}
    try:
        a = ask_json("window_grid", WINDOW_GRID_PROMPT, [_image_bytes(photo, crop)], GridAnswer)
        b = ask_json("facade_grid", FACADE_GRID_PROMPT, [_image_bytes(band)], GridAnswer)
    except GeminiUnavailable as exc:
        return {"skipped": str(exc)}
    items = []
    for k in FINGERPRINT_ITEMS:
        va, vb = getattr(a, k), getattr(b, k)
        items.append({"item": k, "ad": va, "facade": vb, "agree": None if "unclear" in (va, vb) else va == vb})
    agree = sum(1 for i in items if i["agree"])
    return {"items": items, "agree": agree, "of": len(FINGERPRINT_ITEMS),
            "verdict": f"fingerprint agrees ({agree} of 4)" if agree >= 3 else "for analyst review"}


# ------------------------------------------------------------------ plumbing
def _key() -> Optional[str]:
    return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")


def vision_model() -> str:
    explicit = os.environ.get("DOME_VISION_MODEL")
    if explicit:
        return explicit
    provider, _, name = config.MODEL.partition(":")
    return name if provider == "google_genai" and name else "gemini-3.5-flash"


def cache_dir() -> Path:
    """Every Gemini answer lives here (free tier: ~20 requests/day), keyed by a hash of
    prompt version + task + model + prompt + image bytes, and is reused on every rerun."""
    return Path(os.environ.get("DOME_VISION_CACHE", config.ROOT / "cache" / "gemini"))


LEGACY_CACHE = config.ROOT / "cache" / "vision"      # where answers were cached before Nov 15


def is_quota_error(exc: BaseException) -> bool:
    t = f"{type(exc).__name__} {exc}".lower()
    return any(k in t for k in ("429", "resource_exhausted", "resourceexhausted", "quota", "rate limit"))


def log_call(task: str, cached: bool, ok: bool = True, note: str = "") -> None:
    """One line per Gemini request or cache hit in cache/gemini/calls.jsonl (no prompts, no
    images, no keys), so a rerun can prove it made zero live calls."""
    if os.environ.get("DOME_OFFLINE") == "1":            # the offline bundle is read-only
        return
    try:
        d = cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / "calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": __import__("time").time(), "task": task, "cached": cached,
                                "ok": ok, "note": note[:120]}) + "\n")
    except OSError:
        pass


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else config.ROOT / p


def _image_bytes(path: Path, crop: Optional[list[int]] = None) -> tuple[bytes, str]:
    """JPEG bytes, optionally cropped (0-1000 box) and downscaled for the API."""
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        if crop:
            w, h = im.size
            y0, x0, y1, x1 = crop
            im = im.crop((x0 * w // 1000, y0 * h // 1000, x1 * w // 1000, y1 * h // 1000))
        im.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)
        return buf.getvalue(), "image/jpeg"


def _gemini_generate(task: str, model: str, prompt: str, images: list[tuple[bytes, str]]) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=_key())
    parts = [types.Part.from_bytes(data=b, mime_type=m) for b, m in images] + [prompt]
    resp = client.models.generate_content(
        model=model, contents=parts,
        config=types.GenerateContentConfig(temperature=0, seed=0,
                                           response_mime_type="application/json"))
    return resp.text or ""


# Tests swap this for a fake. Signature: (task, model, prompt, images) -> JSON text.
GENERATE: Callable[[str, str, str, list[tuple[bytes, str]]], str] = _gemini_generate


def _parse(text: str, schema: type[BaseModel]) -> BaseModel:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return schema.model_validate(json.loads(text))


def ask_json(task: str, prompt: str, images: list[tuple[bytes, str]],
             schema: type[BaseModel]) -> BaseModel:
    """One cached, validated Gemini answer. Same inputs -> same answer, from disk."""
    model = vision_model()
    h = hashlib.sha256()
    for part in (PROMPT_VERSION, task, model, prompt):
        h.update(part.encode())
    for b, _ in images:
        h.update(hashlib.sha256(b).digest())
    key = h.hexdigest()[:20]
    path = cache_dir() / f"{task}_{key}.json"
    legacy = LEGACY_CACHE / f"{task}_{key}.json"
    if not path.exists() and legacy.exists() and "DOME_VISION_CACHE" not in os.environ:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(legacy.read_bytes())          # same key scheme: reuse, don't re-ask
    if path.exists():
        try:
            answer = schema.model_validate(json.loads(path.read_text(encoding="utf-8"))["answer"])
            log_call(task, cached=True)
            return answer
        except (ValidationError, KeyError, json.JSONDecodeError):
            log.warning("ignoring unreadable cache file %s", path)
    if os.environ.get("DOME_OFFLINE") == "1":
        raise GeminiUnavailable(f"{task}: not recorded in the offline demo")
    if not _key():
        raise GeminiUnavailable(f"{task}: no GOOGLE_API_KEY and no cached answer")
    last: Exception | None = None
    for _ in range(2):                       # one retry on a malformed answer
        try:
            answer = _parse(GENERATE(task, model, prompt, images), schema)
            log_call(task, cached=False)
            break
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            last = exc
            log_call(task, cached=False, ok=False, note="malformed answer")
        except Exception as exc:              # API / network / quota: nothing cached to fall back on
            quota = is_quota_error(exc)
            log_call(task, cached=False, ok=False, note="quota" if quota else type(exc).__name__)
            reason = "Gemini quota reached, no cached answer" if quota else f"{type(exc).__name__}: {exc}"
            raise GeminiUnavailable(f"{task}: {reason}"[:300]) from exc
    else:
        raise GeminiUnavailable(f"{task}: malformed answer twice ({last})")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"task": task, "model": model, "prompt_version": PROMPT_VERSION,
                                "answer": answer.model_dump()}, indent=2), encoding="utf-8")
    return answer


# ------------------------------------------------------------------ photo cues
NEUTRAL_CUES = {"setting": "unknown", "window_floor_est": None, "features": [], "source": "none"}


def _clean_features(features: list[str]) -> list[str]:
    out = []
    for f in features:
        f = re.sub(r"[^a-z0-9 \-]", "", f.lower()).strip()[:40]
        if f and f not in out:
            out.append(f)
    return out[:8]


def photo_cues(photo_paths: list[str], stub: Callable[[], dict]) -> dict:
    files = sorted({str(resolve(p)) for p in photo_paths if resolve(p).is_file()})[:MAX_CUE_PHOTOS]
    if not files:
        return {**stub(), "source": "stub"}       # pure stub demo: no image files at all
    try:
        a = ask_json("photo_cues", CUES_PROMPT, [_image_bytes(Path(f)) for f in files], CuesAnswer)
    except GeminiUnavailable as exc:
        log.warning("photo_cues: %s; using neutral cues", exc)
        return dict(NEUTRAL_CUES)
    est = None
    if a.window_visible and a.window_floor_lo and a.window_floor_hi:
        lo, hi = sorted((a.window_floor_lo, a.window_floor_hi))
        est = [lo, hi]
    return {"setting": a.setting, "window_floor_est": est,
            "features": _clean_features(a.features), "source": "gemini"}


# ------------------------------------------------------------------ window check
def _valid_box(box: Optional[list[int]]) -> Optional[list[int]]:
    if not box or len(box) != 4:
        return None
    y0, x0, y1, x1 = (max(0, min(1000, int(v))) for v in box)
    if y1 - y0 < 50 or x1 - x0 < 50:          # too small to be a usable window crop
        return None
    return [y0, x0, y1, x1]


def compare(view: ViewAnswer, oblique: ObliqueAnswer) -> dict:
    """Pure code: which fixed items agree, W, and a floor range. No model involved."""
    checks: dict[str, bool] = {}
    reasons: list[str] = []
    items: list[dict] = []
    for item in WINDOW_ITEMS:
        v, o = getattr(view, item), getattr(oblique, item)
        items.append({"item": item, "ad": v, "oblique": o, "agree": None if "unclear" in (v, o) else v == o})
        if "unclear" in (v, o):
            continue
        checks[item] = v == o
        reasons.append(f"{item.replace('_', ' ')}: window {v}, oblique {o}")
    floor_range = None
    if view.height_above_street != "unclear":
        lo, hi = HEIGHT_FLOORS[view.height_above_street]
        if oblique.facade_floors:
            checks["height_above_street"] = lo <= oblique.facade_floors
            items.append({"item": "height_above_street", "ad": view.height_above_street,
                          "oblique": f"{oblique.facade_floors} floors", "agree": lo <= oblique.facade_floors})
            reasons.append(f"height: window looks {view.height_above_street} "
                           f"(floor {lo}+), building has {oblique.facade_floors} floors")
            hi = min(hi, oblique.facade_floors)
        floor_range = [lo, hi] if lo <= hi else None
    decided = len(checks)
    W = round(sum(checks.values()) / decided, 2) if decided >= MIN_DECIDED_ITEMS else None
    return {"W": W, "checks": checks, "floor_range": floor_range, "reasons": reasons,
            "decided": decided, "items": items}


def window_check(photo_path: str, lat: float, lon: float, heading_deg: float,
                 stub: Callable[[], dict], oblique_view: Callable[[float, float, float], str]) -> dict:
    """W = share of fixed items on which the window view and the oblique agree.

    Returns W = None (with `skipped`) whenever the check cannot run honestly.
    """
    from ._common import use_stubs
    photo = resolve(photo_path)
    if not photo.is_file() or use_stubs():
        return stub()                              # stub data tools (DOME_STUBS=1) or no image files
    try:
        oblique = resolve(oblique_view(lat, lon, heading_deg))
    except Exception as exc:
        return {"W": None, "checks": {}, "floor_range": None,
                "skipped": f"oblique_view failed: {type(exc).__name__}: {exc}"[:200]}
    if not oblique.is_file():
        return {"W": None, "checks": {}, "floor_range": None,
                "skipped": f"no oblique image at {oblique.name}"}
    try:
        box = ask_json("window_box", BOX_PROMPT, [_image_bytes(photo)], BoxAnswer)
        crop = _valid_box(box.box) if box.window_visible else None
        if box.window_visible is False:
            return {"W": None, "checks": {}, "floor_range": None,
                    "skipped": "no window to the outside found in the photo"}
        view = ask_json("window_view", VIEW_PROMPT, [_image_bytes(photo, crop)], ViewAnswer)
        obl = ask_json("oblique_view", OBLIQUE_PROMPT, [_image_bytes(oblique)], ObliqueAnswer)
    except GeminiUnavailable as exc:
        return {"W": None, "checks": {}, "floor_range": None, "skipped": str(exc)}
    out = compare(view, obl)
    if out["W"] is None:
        out["skipped"] = f"only {out['decided']} items could be compared (need {MIN_DECIDED_ITEMS})"
    out["cropped"] = crop is not None
    out["photo"], out["oblique"], out["crop_box"] = str(photo), str(oblique), crop
    return out
