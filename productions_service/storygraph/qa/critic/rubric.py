"""Structured VLM output contract (`ClipRubric`) for spec-aware clip QA.

Every verdict field is REQUIRED (no defaults) so a structured-output VLM cannot silently omit a
check and produce a false pass. Lists (not dicts) are used because Gemini response schemas cannot
express free-form dict keys — the root cause of `face_similarity == {}` on every shot.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from .spec import CriticSpec

RUBRIC_VERSION = "clip-rubric-v1"
RUBRIC_KEYS_PREFIX = "RUBRIC_KEYS="
_KEYS_RE = re.compile(r"^RUBRIC_KEYS=(\{.*\})\s*$", re.MULTILINE)


class StepVerdict(BaseModel):
    n: int
    done: bool
    evidence: str = Field(
        description="Observed fact with timestamps, e.g. 't=2.5-3.0s'."
    )
    spec_conflict: bool = Field(
        description="True only if the spec itself makes this step impossible."
    )


class IdentityVerdict(BaseModel):
    subject: str
    score: float = Field(description="0..1 match of the clip subject vs its REFERENCE.")
    drift: bool
    evidence: str


class ObjectVerdict(BaseModel):
    object: str
    max_instances_seen: int
    start_matches: bool
    end_matches: bool
    evidence: str
    spec_conflict: bool


class CameraVerdict(BaseModel):
    observed: str
    size_matches: bool
    angle_matches: bool
    move_matches: bool
    spec_conflict: bool


class ContinuityVerdict(BaseModel):
    applicable: bool
    setting_layout_matches: bool
    positions_match: bool
    evidence: str


class SpeechVerdict(BaseModel):
    subject: str
    mouth_moving: bool
    evidence: str


class ClipRubric(BaseModel):
    """One verdict per spec step / subject / object, plus clip-level checks."""

    steps: list[StepVerdict]
    identities: list[IdentityVerdict]
    objects: list[ObjectVerdict]
    camera: CameraVerdict
    hard_cut_seen: bool
    hard_cut_evidence: str
    continuity: ContinuityVerdict
    style_drift: bool
    style_evidence: str
    speech: list[SpeechVerdict]
    setting_match: float
    wardrobe_match: float
    physics_plausibility: float
    drift_flags: list[str]

    @classmethod
    def mock_response(cls, prompt: str, passing: bool = True) -> ClipRubric:
        """Deterministic rubric covering every RUBRIC_KEYS item (offline MockVLMProvider)."""
        keys = read_rubric_keys(prompt)
        rubric = cls(
            steps=[_ok_step(int(n)) for n in keys.get("steps", [])],
            identities=[_ok_identity(s) for s in keys.get("subjects", [])],
            objects=[_ok_object(o) for o in keys.get("objects", [])],
            camera=CameraVerdict(
                observed="as specified",
                size_matches=True,
                angle_matches=True,
                move_matches=True,
                spec_conflict=False,
            ),
            hard_cut_seen=False,
            hard_cut_evidence="",
            continuity=ContinuityVerdict(
                applicable=bool(keys.get("continuity")),
                setting_layout_matches=True,
                positions_match=True,
                evidence="layout matches previous last frame",
            ),
            style_drift=False,
            style_evidence="",
            speech=[_speech(s, keys) for s in keys.get("subjects", [])],
            setting_match=0.94,
            wardrobe_match=0.92,
            physics_plausibility=0.9,
            drift_flags=[],
        )
        return rubric if passing else _degrade(rubric)


def _ok_step(n: int) -> StepVerdict:
    return StepVerdict(n=n, done=True, evidence="step visible", spec_conflict=False)


def _ok_identity(subject: str) -> IdentityVerdict:
    return IdentityVerdict(subject=subject, score=0.91, drift=False, evidence="matches")


def _ok_object(name: str) -> ObjectVerdict:
    return ObjectVerdict(
        object=name,
        max_instances_seen=1,
        start_matches=True,
        end_matches=True,
        evidence="single instance, placement as specified",
        spec_conflict=False,
    )


def _speech(subject: str, keys: dict[str, Any]) -> SpeechVerdict:
    speaks = subject in keys.get("speakers", [])
    return SpeechVerdict(subject=subject, mouth_moving=speaks, evidence="")


def _degrade(rubric: ClipRubric) -> ClipRubric:
    """Scripted first-attempt failure: wardrobe below threshold plus a drift flag."""
    return rubric.model_copy(
        update={
            "wardrobe_match": 0.6,
            "drift_flags": ["wardrobe_mismatch_on_attempt_1"],
        }
    )


def rubric_keys_line(spec: CriticSpec, has_prev_frame: bool) -> str:
    """Machine-readable list of items the VLM must return exactly one verdict for."""
    keys = {
        "steps": [s.n for s in spec.steps],
        "subjects": [s.name for s in spec.subjects],
        "objects": [o.name for o in spec.objects],
        "speakers": spec.speakers,
        "continuity": has_prev_frame,
    }
    return RUBRIC_KEYS_PREFIX + json.dumps(keys, separators=(",", ":"))


def read_rubric_keys(prompt: str) -> dict[str, Any]:
    """Parse the RUBRIC_KEYS line back out of a critic prompt (empty dict if absent)."""
    match = _KEYS_RE.search(prompt or "")
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
