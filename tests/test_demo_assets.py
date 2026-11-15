"""Demo asset pack for the Ring A scan (real data; skips without cache/keys)."""
import json

import pytest

from dome.data_tools._common import REPO_ROOT
from tests.test_data_tools import needs_keys

KEYS = {"display_name", "costar", "footprint_geojson", "rough_pin", "fixed_pin", "ortho", "obliques",
        "floor", "floor_source", "matched_sweep", "matches", "matterport_embed"}


def _walk_keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_keys(v)


def _imgs(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("img", "floorplan_img", "match_img") and isinstance(v, str):
                yield v
            elif k == "faces" and isinstance(v, list):
                yield from v
            else:
                yield from _imgs(v)
    elif isinstance(o, list):
        for v in o:
            yield from _imgs(v)


@pytest.mark.real
@needs_keys
@pytest.mark.skipif(not (REPO_ROOT / "cache").exists(), reason="cache/ missing")
def test_pack_ring_a():
    from dome.tools import demo_assets
    pack = json.loads(demo_assets.build("LqCMcmmVH3d").read_text())
    assert KEYS <= set(pack)
    assert not any("address" in k.lower() or "street" in k.lower() for k in _walk_keys(pack))
    assert pack["floor"] == 3
    for p in _imgs(pack):
        assert (REPO_ROOT / p).exists(), p
