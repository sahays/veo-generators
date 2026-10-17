"""Feature routers package — re-exports domain router submodules."""

from __future__ import annotations

import sys

from routers.core import auth, chat, diagnostics, models, pricing, system
from routers.media import (
    adapts,
    dubbing,
    key_moments,
    promo,
    reframe,
    thumbnails,
    uploads,
)
from routers.studio import avatars, avatars_live, productions, render, scenes

_SUBMODULES = {
    "adapts": adapts,
    "auth": auth,
    "avatars": avatars,
    "avatars_live": avatars_live,
    "chat": chat,
    "diagnostics": diagnostics,
    "dubbing": dubbing,
    "key_moments": key_moments,
    "models": models,
    "pricing": pricing,
    "productions": productions,
    "promo": promo,
    "reframe": reframe,
    "render": render,
    "scenes": scenes,
    "system": system,
    "thumbnails": thumbnails,
    "uploads": uploads,
}

for _name, _mod in _SUBMODULES.items():
    sys.modules.setdefault(f"routers.{_name}", _mod)

__all__ = list(_SUBMODULES.keys())
