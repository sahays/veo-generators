"""Typed machine-instruction schema for one Gemini Omni clip (`OmniClipSpec`).

`OmniClipSpec` is the internal, validated model: linting, prompt versioning, repair
patches and the critic's expectations all operate on it. `render()` is its compact JSON
(stable key order, `None` fields omitted) stored as `PromptVersion.spec_json`; the text sent
to Omni is a deterministic rendering of it in a `PromptFormat` (`omni/render.py`).
Cross-references use short symbolic ids (`S#` subjects, `O#` objects, `L#` setting); image
references use the adapter's role tags (`FIRST_FRAME`, `IMAGE_REF_k`). Step order in
`sequence` is the only temporal signal.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..schemas.generation import PromptFormat  # noqa: F401  (re-exported for omni users)

RepairToken = Literal[
    "character_design_matches_refs",
    "objects_persist_whole_take",
    "one_action_at_a_time",
    "screen_positions_locked",
    "camera_locked_static",
    "motion_from_first_frame",
    "single_consistent_art_style",
]
ConstraintToken = Literal[
    "sequence_order_strict",
    "single_continuous_take",
    "each_object_single_instance",
    "objects_static_unless_in_sequence",
    "no_text_overlays",
    "refs_are_identity_only",
    "first_frame_is_opening_frame",
    "lipsync_active_speaker_only",
    RepairToken,
]
ActorKindToken = Literal["robot", "animal", "hybrid", "person"]


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AudioSpec(_Spec):
    music: bool = False
    sfx: list[str] | None = None


class ClipSpec(_Spec):
    duration_s: float
    aspect: str
    fps: int
    style: str | None = None
    audio: AudioSpec


class SubjectSpec(_Spec):
    id: str
    name: str
    kind: ActorKindToken
    ref_image: str | None = None
    identity: str | None = None
    wardrobe: str | None = None
    holding: str | None = None
    screen_pos: str
    framing: str
    can_speak: bool
    has_mouth: bool
    vocal: str | None = None


class SettingSpec(_Spec):
    id: str
    name: str
    ref_image: str | None = None
    identity: str | None = None
    time_of_day: str | None = None
    weather: str | None = None


class ObjectState(_Spec):
    """Concrete plain-word state: a location (`where`) or holder, plus state words."""

    where: str | None = None
    held_by: str | None = None
    condition: str | None = None


class ObjectSpec(_Spec):
    """`in_frame` is False for set dressing the shot framing excludes (e.g. in a close-up):
    the object still exists offscreen, but QA must not expect to see it."""

    id: str
    name: str
    ref_image: str | None = None
    identity: str | None = None
    start: ObjectState
    end: ObjectState | None = None
    moves: bool
    in_frame: bool = True


class CameraSpecOut(_Spec):
    size: str
    angle: str
    move: str
    lens_mm: int
    focus: str | None = None
    intent: str | None = None


class LookSpec(_Spec):
    lighting: str | None = None
    color_grade: str | None = None
    mood: str | None = None
    composition: str | None = None


class ContinuitySpec(_Spec):
    first_frame: Literal["FIRST_FRAME"] | None = None
    opening_state: str | None = None


class StepSpec(_Spec):
    n: int
    actor: str
    verb: str
    target: str | None = None
    detail: str | None = None
    end_state: str | None = None


class SpeechSpec(_Spec):
    after: int | None = None
    speaker: str
    lang: str
    text: str
    delivery: str | None = None
    voice: str
    lipsync: bool


class OmniClipSpec(_Spec):
    task: Literal["render_video_clip"] = "render_video_clip"
    clip: ClipSpec
    subjects: list[SubjectSpec] | None = None
    setting: SettingSpec
    objects: list[ObjectSpec] | None = None
    camera: CameraSpecOut
    look: LookSpec | None = None
    continuity: ContinuitySpec | None = None
    sequence: list[StepSpec] | None = None
    summary: str | None = None
    speech: list[SpeechSpec] | None = None
    constraints: list[ConstraintToken]
    must_achieve: list[str] | None = None

    def render(self) -> str:
        """Compact, deterministic JSON (no whitespace, None fields omitted)."""
        return self.model_dump_json(exclude_none=True)
