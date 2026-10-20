"""Shot-scoped symbol table: raw storygraph ids -> short symbolic ids (S#, O#, L#).

Every cross-reference in the Omni spec goes through `Symbols.ref`, so raw graph ids
(`char_*`, `obj_*`, `loc_*`, ...) never reach the prompt. Entities outside the shot fall
back to their canonical/humanized name.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..views import ShotView
from .text import IdResolver, humanize


@dataclass(frozen=True)
class ImageBindings:
    """Adapter image roles for this shot: first-frame slot + entity -> `IMAGE_REF_k` tokens."""

    first_frame: bool = False
    ref_by_entity: dict[str, str] = field(default_factory=dict)


def name_map(view: ShotView) -> dict[str, str]:
    """Canonical names for the location, cast, and props of the shot."""
    names = {view.location.id: view.location.canonical_name}
    names.update({k: e.canonical_name for k, e in view.cast_entities.items()})
    names.update({k: e.canonical_name for k, e in view.prop_entities.items()})
    for c in view.shot.cast:
        names.setdefault(c.entity_id, humanize(c.entity_id.split("_", 1)[-1]))
    return names


def _symbol_ids(view: ShotView) -> dict[str, str]:
    ids = {view.location.id: "L1"}
    cast = dict.fromkeys(c.entity_id for c in view.shot.cast)
    ids.update({eid: f"S{i}" for i, eid in enumerate(cast, 1)})
    ids.update(
        {pid: f"O{i}" for i, pid in enumerate(dict.fromkeys(view.shot.prop_ids), 1)}
    )
    return ids


class Symbols:
    """Resolve entity ids or names to symbolic ids; text through `IdResolver` names."""

    def __init__(self, view: ShotView) -> None:
        names = name_map(view)
        self.ids: dict[str, str] = _symbol_ids(view)
        self.names: dict[str, str] = names
        self.resolver = IdResolver(names)
        self._by_name = {n.lower(): eid for eid, n in names.items() if eid in self.ids}

    def ref(self, key: str | None) -> str | None:
        """Symbolic id for an entity id or canonical name; resolved name otherwise."""
        if not key or not key.strip():
            return None
        raw = key.strip()
        eid = raw if raw in self.ids else self._by_name.get(raw.lower(), "")
        if eid:
            return self.ids[eid]
        return self.resolver(raw).strip() or None

    def name(self, entity_id: str) -> str:
        return self.names.get(entity_id) or self.resolver(entity_id)
