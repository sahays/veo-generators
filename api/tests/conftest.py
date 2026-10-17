"""Pytest configuration ensuring `api/`, its domain packages, and `workers/` are on `sys.path`."""

from __future__ import annotations

import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parent.parent
_WORKERS_DIR = _API_DIR.parent / "workers"
_PATHS = (
    _WORKERS_DIR,
    _API_DIR,
    _API_DIR / "models",
    _API_DIR / "pricing",
    _API_DIR / "dubbing",
    _API_DIR / "reframe",
    _API_DIR / "reframe_core",
    _API_DIR / "media",
    _API_DIR / "services",
)

for _d in reversed(_PATHS):
    _s = str(_d)
    if _s not in sys.path:
        sys.path.insert(0, _s)

import sitecustomize  # noqa: E402, F401
