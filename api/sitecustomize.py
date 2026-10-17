"""Ensure `api/` and its domain subpackages are on `sys.path` when running from `api/`."""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
import types
from collections.abc import Sequence
from pathlib import Path

_API_DIR = Path(__file__).resolve().parent
_DOMAIN_DIRS = (
    _API_DIR,
    _API_DIR / "models",
    _API_DIR / "models" / "domains",
    _API_DIR / "pricing",
    _API_DIR / "dubbing",
    _API_DIR / "dubbing" / "live",
    _API_DIR / "reframe",
    _API_DIR / "reframe_core",
    _API_DIR / "media",
    _API_DIR / "services",
)

for _d in reversed(_DOMAIN_DIRS):
    _s = str(_d)
    if _s not in sys.path:
        sys.path.insert(0, _s)


class _ReframeAliasFinder(importlib.abc.MetaPathFinder):
    """Resolve `reframe_*` imports to `_reframe_*.py` modules across reframe packages."""

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: types.ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if not fullname.startswith("reframe_"):
            return None
        for pkg in ("reframe", "reframe_core"):
            candidate = _API_DIR / pkg / f"_{fullname}.py"
            if candidate.is_file():
                return importlib.util.spec_from_file_location(fullname, candidate)
        return None


if not any(isinstance(f, _ReframeAliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _ReframeAliasFinder())
