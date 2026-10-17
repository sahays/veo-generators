"""Typed Repository (`Repo`) wrapping GraphStore and BlobStore with versioning and staleness propagation."""

from __future__ import annotations

from .service import Repo, T
from .versioning import (
    _VERSION_SUFFIX_RE,
    mint_versioned_appearance,
    mint_versioned_asset,
    persist_shot_with_refs,
    propagate_staleness,
    strip_version_suffix as _strip_version_suffix,
)

__all__ = [
    "Repo",
    "T",
    "_VERSION_SUFFIX_RE",
    "_strip_version_suffix",
    "mint_versioned_appearance",
    "mint_versioned_asset",
    "persist_shot_with_refs",
    "propagate_staleness",
]
