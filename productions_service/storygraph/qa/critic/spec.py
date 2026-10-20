"""Lenient, typed view of the compiled `OmniClipSpec` JSON used as the critic's ground truth.

The critic judges a clip ONLY against the spec that was actually sent to the renderer
(`GenerationRun.compiled_prompt`). Parsing is dict-based so additive spec-schema changes from
other phases never break QA; symbolic ids (`S#`, `O#`, `L#`) are resolved to display names.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

_SINGLE_TAKE_TOKEN = "single_continuous_take"
_RAW_SPEC_MAX_CHARS = 6000


class SpecStep(BaseModel):
    n: int
    actor: str
    text: str
    end_state: str = ""


class SpecSubject(BaseModel):
    sid: str
    name: str
    has_ref: bool = False
    can_speak: bool = False
    has_mouth: bool = False


class SpecObject(BaseModel):
    oid: str
    name: str
    has_ref: bool = False
    start: str = ""
    end: str = ""
    in_frame: bool = True  # False = offscreen set dressing (not expected in view)


class SpecCamera(BaseModel):
    size: str = ""
    angle: str = ""
    move: str = ""


class CriticSpec(BaseModel):
    """Everything the critic may judge for one clip (and nothing outside it)."""

    raw_json: str = ""
    parsed: bool = False
    duration_s: float = 0.0
    steps: list[SpecStep] = Field(default_factory=list)
    subjects: list[SpecSubject] = Field(default_factory=list)
    objects: list[SpecObject] = Field(default_factory=list)
    camera: SpecCamera = Field(default_factory=SpecCamera)
    speakers: list[str] = Field(default_factory=list)
    single_take: bool = True
    chained_first_frame: bool = False
    has_setting_ref: bool = False

    def subject(self, name: str) -> SpecSubject | None:
        """Return the spec subject whose display name matches `name` (case-insensitive)."""
        key = name.strip().lower()
        return next((s for s in self.subjects if s.name.lower() == key), None)

    def object_named(self, name: str) -> SpecObject | None:
        """Return the spec object whose display name matches `name` (case-insensitive)."""
        key = name.strip().lower()
        return next((o for o in self.objects if o.name.lower() == key), None)


def _symbol_names(data: dict[str, Any]) -> dict[str, str]:
    """Map symbolic ids (`S1`, `O2`, `L1`) to display names."""
    names: dict[str, str] = {}
    for key in ("subjects", "objects"):
        for item in data.get(key) or []:
            if isinstance(item, dict) and item.get("id"):
                names[str(item["id"])] = str(item.get("name") or item["id"])
    setting = data.get("setting")
    if isinstance(setting, dict) and setting.get("id"):
        names[str(setting["id"])] = str(setting.get("name") or setting["id"])
    return names


def _resolve(names: dict[str, str], token: object) -> str:
    """Resolve a symbolic id to its display name (pass-through for plain text)."""
    text = str(token or "").strip()
    return names.get(text, text)


def _object_state_text(names: dict[str, str], state: object) -> str:
    """Render an `ObjectState` dict as observable text ('held by Pip' / 'tipped, on the table')."""
    if not isinstance(state, dict):
        return ""
    holder = state.get("held_by")
    place = (
        f"held by {_resolve(names, holder)}"
        if holder
        else str(state.get("where") or "")
    )
    condition = str(state.get("condition") or "").strip()
    return ", ".join(p for p in (condition, place) if p)


def _parse_steps(data: dict[str, Any], names: dict[str, str]) -> list[SpecStep]:
    """Turn spec `sequence` entries into human-checkable step descriptions."""
    steps: list[SpecStep] = []
    for raw in data.get("sequence") or []:
        if not isinstance(raw, dict):
            continue
        actor = _resolve(names, raw.get("actor"))
        parts = [actor, str(raw.get("verb") or ""), _resolve(names, raw.get("target"))]
        detail = str(raw.get("detail") or "")
        text = " ".join(p for p in parts if p) + (f" ({detail})" if detail else "")
        steps.append(
            SpecStep(
                n=int(raw.get("n") or len(steps) + 1),
                actor=actor,
                text=text,
                end_state=str(raw.get("end_state") or ""),
            )
        )
    return steps


def _parse_subjects(data: dict[str, Any]) -> list[SpecSubject]:
    """Extract spec subjects with their reference/speech capabilities."""
    return [
        SpecSubject(
            sid=str(s.get("id") or ""),
            name=str(s.get("name") or s.get("id") or ""),
            has_ref=bool(s.get("ref_image")),
            can_speak=bool(s.get("can_speak")),
            has_mouth=bool(s.get("has_mouth")),
        )
        for s in data.get("subjects") or []
        if isinstance(s, dict)
    ]


def _parse_objects(data: dict[str, Any], names: dict[str, str]) -> list[SpecObject]:
    """Extract spec objects with start/end placement text and the in-frame expectation."""
    return [
        SpecObject(
            oid=str(o.get("id") or ""),
            name=str(o.get("name") or o.get("id") or ""),
            has_ref=bool(o.get("ref_image")),
            start=_object_state_text(names, o.get("start")),
            end=_object_state_text(names, o.get("end")),
            in_frame=o.get("in_frame") is not False,
        )
        for o in data.get("objects") or []
        if isinstance(o, dict)
    ]


def _parse_camera(data: dict[str, Any]) -> SpecCamera:
    """Extract the camera size/angle/move contract."""
    cam = data.get("camera")
    if not isinstance(cam, dict):
        return SpecCamera()
    return SpecCamera(
        size=str(cam.get("size") or ""),
        angle=str(cam.get("angle") or ""),
        move=str(cam.get("move") or ""),
    )


def _parse_speakers(data: dict[str, Any], names: dict[str, str]) -> list[str]:
    """Return the ordered, unique display names of subjects with spoken lines."""
    speakers = [
        _resolve(names, line.get("speaker"))
        for line in data.get("speech") or []
        if isinstance(line, dict) and line.get("text")
    ]
    return list(dict.fromkeys(s for s in speakers if s))


def _from_dict(data: dict[str, Any], raw: str) -> CriticSpec:
    """Build a `CriticSpec` from a decoded OmniClipSpec dict."""
    names = _symbol_names(data)
    clip = data.get("clip") if isinstance(data.get("clip"), dict) else {}
    continuity = data.get("continuity")
    setting = data.get("setting")
    constraints = [str(c) for c in data.get("constraints") or []]
    return CriticSpec(
        raw_json=raw[:_RAW_SPEC_MAX_CHARS],
        parsed=True,
        duration_s=float(clip.get("duration_s") or 0.0),
        steps=_parse_steps(data, names),
        subjects=_parse_subjects(data),
        objects=_parse_objects(data, names),
        camera=_parse_camera(data),
        speakers=_parse_speakers(data, names),
        single_take=_SINGLE_TAKE_TOKEN in constraints or not constraints,
        chained_first_frame=isinstance(continuity, dict)
        and bool(continuity.get("first_frame")),
        has_setting_ref=isinstance(setting, dict) and bool(setting.get("ref_image")),
    )


def parse_compiled_spec(compiled_prompt: str) -> CriticSpec:
    """Parse `GenerationRun.compiled_prompt`; non-JSON prompts yield an unparsed spec."""
    text = (compiled_prompt or "").strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return CriticSpec(raw_json=text[:_RAW_SPEC_MAX_CHARS])
    if not isinstance(data, dict):
        return CriticSpec(raw_json=text[:_RAW_SPEC_MAX_CHARS])
    return _from_dict(data, text)
