"""Dome: flagged synthetic accounts -> ranked, explained building leads for human verification."""

import os as _os

if _os.environ.get("DOME_OFFLINE") == "1":      # offline demo: bundle only, no keys, no network
    from . import offline as _offline
    _offline.setup()
