"""Backward-compatible shim: final assembly now lives in `storygraph.assembly`."""

from __future__ import annotations

from .assembly import assemble

__all__ = ["assemble"]
