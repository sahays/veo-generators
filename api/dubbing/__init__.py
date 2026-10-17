"""Ensure `api/dubbing/live` is on `sys.path` when `dubbing` package is imported."""

from __future__ import annotations

import sys
from pathlib import Path

_LIVE_DIR = str(Path(__file__).resolve().parent / "live")
if _LIVE_DIR not in sys.path:
    sys.path.insert(0, _LIVE_DIR)
