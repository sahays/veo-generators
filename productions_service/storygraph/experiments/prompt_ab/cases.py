"""Build `ShotCase`s from production exports (Firestore REST dumps or plain JSON lists).

The compiled spec, reference asset ids and labels are reconstructed exactly as the pipeline
built them, and `binding_mismatches` proves the spec's `IMAGE_REF_k` tokens still point at
the images the adapter will send (same `plan_image_slots` the compiler used).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...adapters.omni.inputs import plan_image_slots
from ...adapters.omni.package import RefLabel, RefRole
from ...omni.spec import OmniClipSpec
from .contracts import ShotCase, ShotCategory

MAX_IMAGES = 6
_SCALARS = ("stringValue", "booleanValue", "doubleValue", "timestampValue")


def _decode(value: Any) -> Any:
    """Decode one Firestore REST typed value into plain Python."""
    if not isinstance(value, dict):
        return value
    for key in _SCALARS:
        if key in value:
            return value[key]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "nullValue" in value:
        return None
    if "arrayValue" in value:
        return [_decode(v) for v in value["arrayValue"].get("values", [])]
    if "mapValue" in value:
        return {k: _decode(v) for k, v in value["mapValue"].get("fields", {}).items()}
    return value


def load_records(path: Path) -> list[dict[str, Any]]:
    """Plain records from a `{documents: [...]}` REST dump or a plain JSON list."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "documents" in raw:
        return [
            {k: _decode(v) for k, v in doc.get("fields", {}).items()}
            for doc in raw["documents"]
        ]
    return list(raw) if isinstance(raw, list) else [raw]


def index_by(records: list[dict[str, Any]], key: str = "id") -> dict[str, dict]:
    return {str(r.get(key) or r.get("_id")): r for r in records}


def _role(asset: dict[str, Any]) -> RefRole:
    ids: list[str] = asset.get("depicts_entity_ids") or []
    kind = str(asset.get("kind") or "")
    if kind == "composite_sheet":
        return "composite"
    if any(i.startswith("char_") for i in ids):
        return "character"
    if any(i.startswith("obj_") for i in ids):
        return "prop"
    if kind == "location_plate" or any(i.startswith("loc_") for i in ids):
        return "location"
    return "other"


def build_labels(
    asset_ids: list[str],
    assets: dict[str, dict],
    entities: dict[str, dict],
    speaking: set[str],
) -> tuple[RefLabel, ...]:
    """RefLabels in run order, mirroring `adapters.omni.package.build_ref_labels`."""
    out: list[RefLabel] = []
    for aid in asset_ids:
        asset = assets[aid]
        ids: list[str] = asset.get("depicts_entity_ids") or []
        names = tuple(
            str(entities.get(i, {}).get("canonical_name") or i) for i in ids
        ) or (aid,)
        out.append(
            RefLabel(
                uri=str(asset["uri"]),
                asset_id=aid,
                names=names,
                role=_role(asset),
                speaking=bool(speaking & set(ids)),
            )
        )
    return tuple(out)


def speaking_ids(shot: dict[str, Any]) -> set[str]:
    return {str(c["entity_id"]) for c in shot.get("cast") or [] if c.get("speaking")}


@dataclass(frozen=True)
class CaseSource:
    """Inputs for one case: the chosen run plus its project-level lookup tables."""

    case_id: str
    category: ShotCategory
    project_id: str
    run: dict[str, Any]
    shot: dict[str, Any]
    assets: dict[str, dict]
    entities: dict[str, dict]
    first_frame_uri: str | None = None
    prev_frame_path: str | None = None
    visual_style_preset: str = ""
    language: str = ""


def build_case(src: CaseSource) -> ShotCase:
    """Assemble a `ShotCase`; the spec is the run's compiled prompt, untouched."""
    labels = build_labels(
        list(src.run["reference_asset_ids"]),
        src.assets,
        src.entities,
        speaking_ids(src.shot),
    )
    return ShotCase(
        case_id=src.case_id,
        project_id=src.project_id,
        shot_id=str(src.run["shot_id"]),
        category=src.category,
        spec_json=str(src.run.get("spec_json") or src.run["compiled_prompt"]),
        labels=labels,
        first_frame_uri=src.first_frame_uri,
        prev_frame_path=src.prev_frame_path,
        visual_style_preset=src.visual_style_preset,
        language=src.language,
    )


def _spec_refs(spec: OmniClipSpec) -> list[tuple[str, str]]:
    """(IMAGE_REF token, entity name) for every image-bound spec entity."""
    items: list[tuple[str | None, str]] = [
        (s.ref_image, s.name) for s in spec.subjects or []
    ]
    items += [(o.ref_image, o.name) for o in spec.objects or []]
    items.append((spec.setting.ref_image, spec.setting.name))
    return [(tok, name) for tok, name in items if tok]


def binding_mismatches(case: ShotCase) -> list[str]:
    """Spec tokens whose request slot depicts a different entity (empty = bound correctly)."""
    spec = OmniClipSpec.model_validate_json(case.spec_json)
    slots = plan_image_slots(list(case.labels), case.first_frame_uri, MAX_IMAGES)
    by_token = {f"IMAGE_REF_{k}": lbl for k, lbl in enumerate(slots.refs)}
    bad: list[str] = []
    for token, name in _spec_refs(spec):
        lbl = by_token.get(token)
        if lbl is None or name.lower() not in " ".join(lbl.names).lower():
            got = lbl.names if lbl else "unsent"
            bad.append(f"{token}: spec={name!r} slot={got}")
    return bad
