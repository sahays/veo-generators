"""Typed Repository (`Repo`) wrapping GraphStore and BlobStore with versioning and staleness propagation."""

from __future__ import annotations

from .service import Repo, T
from .versioning import (
    _VERSION_SUFFIX_RE,
    mint_versioned_appearance,
    mint_versioned_asset,
    persist_shot_with_refs,
    propagate_staleness,
)
from .versioning import (
    strip_version_suffix as _strip_version_suffix,
)

__all__ = [
    "_VERSION_SUFFIX_RE",
    "Repo",
    "T",
    "_strip_version_suffix",
    "mint_versioned_appearance",
    "mint_versioned_asset",
    "persist_shot_with_refs",
    "propagate_staleness",
]
