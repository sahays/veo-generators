"""Render-time package enrichment: per-reference identity labels and project safety context.

`compile_shot` produces a `Package` whose `reference_uris` are bare URIs. The Omni adapter needs
to know *who* each image depicts (to label it inline and to order character identities before
props) and which project preset/language governs safety rewrites. `RenderPackage` carries that
context without changing the compiler contract or the package hash.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Literal

from ...compile import Package
from ...schema import Asset
from ...views import ShotView

RefRole = Literal["character", "composite", "location", "prop", "other"]


@dataclass(frozen=True)
class RefLabel:
    """Identity metadata for one reference image slot."""

    uri: str
    asset_id: str
    names: tuple[str, ...]
    role: RefRole
    speaking: bool = False


@dataclass(frozen=True)
class RenderPackage(Package):
    """`Package` plus render-only context consumed by video adapters (not hashed)."""

    reference_labels: tuple[RefLabel, ...] = ()
    project_id: str = ""
    visual_style_preset: str = ""
    language: str = ""


def _speaking_ids(view: ShotView) -> set[str]:
    return {c.entity_id for c in view.shot.cast if c.speaking} | {
        dl.speaker_id for dl in view.dialogue_lines
    }


def _name_for(view: ShotView, entity_id: str) -> str:
    if entity_id in view.cast_entities:
        return view.cast_entities[entity_id].canonical_name
    if entity_id in view.prop_entities:
        return view.prop_entities[entity_id].canonical_name
    if entity_id == view.location.id:
        return view.location.canonical_name
    return entity_id


def _role_for(view: ShotView, asset: Asset) -> RefRole:
    ids = asset.depicts_entity_ids
    if asset.kind == "composite_sheet":
        return "composite"
    if any(i in view.cast_entities for i in ids):
        return "character"
    if any(i in view.prop_entities for i in ids):
        return "prop"
    if view.location.id in ids or asset.kind == "location_plate":
        return "location"
    return "other"


def build_ref_labels(view: ShotView, assets: list[Asset]) -> tuple[RefLabel, ...]:
    """Label each selected reference asset with depicted names, role, and speaking status."""
    speaking = _speaking_ids(view)
    return tuple(
        RefLabel(
            uri=a.uri,
            asset_id=a.id,
            names=tuple(_name_for(view, i) for i in a.depicts_entity_ids) or (a.id,),
            role=_role_for(view, a),
            speaking=bool(speaking & set(a.depicts_entity_ids)),
        )
        for a in assets
    )


def to_render_package(
    pkg: Package,
    labels: tuple[RefLabel, ...],
    project_id: str,
    visual_style_preset: str,
    language: str,
) -> RenderPackage:
    """Return `pkg` enriched with reference labels and project safety context."""
    base = {f.name: getattr(pkg, f.name) for f in fields(Package)}
    return RenderPackage(
        **base,
        reference_labels=labels,
        project_id=project_id,
        visual_style_preset=visual_style_preset,
        language=language,
    )
