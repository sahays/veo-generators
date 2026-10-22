"""Omni request packages for the keyframe render strategies (pure).

* keyframe_interp: one package per segment `(a, b)` with `<FIRST_FRAME>` = keyframe `a`,
  `<LAST_FRAME>` = keyframe `b`, duration `b - a`, and a prompt naming only the motion of the
  beats active inside the segment;
* keyframe_anchored (D1): ONE package per clip, `<FIRST_FRAME>` = keyframe 0, `<LAST_FRAME>` =
  keyframe N, evenly spaced middle keyframes as timed `IMAGE_REF_k` *state references* (as many
  as the image cap allows) and a short spec prompt (images carry identity/wardrobe/props);
* keyframe_anchored_text (D2): first/last keyframes only; the middle states become timeline
  text derived from the plan (no middle images, so nothing can be flashed in as an insert);
* animatic_edit: one package whose `<VIDEO_0>` is the 1 fps animatic, with a short "animate
  into smooth continuous motion, keep everything else the same" prompt (Omni docs: simple
  prompts work best for edits). Identity sheets stay bound as `IMAGE_REF_k` in both.
Prompts are plain text (no spec JSON), so the adapter only sanitizes them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from ...adapters.omni.package import RefLabel, RenderPackage, to_render_package
from ...compile import Package
from ...omni.render import parse_spec
from ..plan.models import KeyframePlan, PlanInput
from .anchored import anchor_times, render_anchored, timeline_lines

_KEEP = (
    "Keep the characters, their faces and outfits, every object and the room layout exactly "
    "identical; each object appears exactly once. Use the reference images for identity only."
)
_SHOT = "A single continuous shot, no scene cuts, no on-screen text, no dialogue."
_CAMERA = {
    "static": "Static camera.",
    "handheld": "Gentle handheld camera.",
    "dolly_in": "Slow dolly-in.",
    "dolly_out": "Slow dolly-out.",
    "pan_l": "Slow pan left.",
    "pan_r": "Slow pan right.",
    "tilt_up": "Slow tilt up.",
    "tilt_down": "Slow tilt down.",
    "track": "Smooth tracking camera.",
}


def _camera_line(inp: PlanInput) -> str:
    return _CAMERA.get(inp.camera.movement, "Steady camera.")


def segment_actions(inp: PlanInput, start: float, end: float) -> list[str]:
    """Actions of the beats overlapping `[start, end)` seconds, in order."""
    return [b.action for b in inp.beats if b.t_start < end and b.t_end > start]


def segment_prompt(inp: PlanInput, start: int, end: int) -> str:
    actions = " Then ".join(segment_actions(inp, float(start), float(end)))
    return " ".join(
        [
            f"Animate smoothly from the first frame to the final frame over {end - start} seconds.",
            f"Action: {actions}" if actions else "Subtle natural idle motion.",
            _camera_line(inp),
            _KEEP,
            _SHOT,
        ]
    )


def animatic_prompt(inp: PlanInput) -> str:
    return " ".join(
        [
            "Animate this storyboard animatic into smooth, continuous, natural motion.",
            _camera_line(inp),
            _KEEP,
            "Keep everything else the same.",
            _SHOT,
        ]
    )


def interp_packages(
    base: Package,
    inp: PlanInput,
    uris: Sequence[str],
    bounds: Sequence[tuple[int, int]],
) -> list[Package]:
    """One interpolation package per segment (keyframe uris indexed by second)."""
    return [
        replace(
            base,
            shot_id=f"{base.shot_id}__seg{k}",
            compiled_prompt=segment_prompt(inp, a, b),
            spec_json="",
            first_frame_uri=uris[a],
            last_frame_uri=uris[b],
            source_video_uri=None,
            duration_s=float(b - a),
        )
        for k, (a, b) in enumerate(bounds)
    ]


def animatic_package(base: Package, inp: PlanInput, video_uri: str) -> Package:
    return replace(
        base,
        compiled_prompt=animatic_prompt(inp),
        spec_json="",
        first_frame_uri=None,
        last_frame_uri=None,
        source_video_uri=video_uri,
        duration_s=inp.duration_s,
    )


def plan_durations(
    plan: KeyframePlan, bounds: Sequence[tuple[int, int]]
) -> list[float]:
    """Planned seconds per segment; the last ends at the clip duration."""
    out = [float(b - a) for a, b in bounds]
    if out:
        out[-1] = round(plan.duration_s - bounds[-1][0], 3)
    return out


def _keyframe_labels(uris: Sequence[str], times: Sequence[int]) -> tuple[RefLabel, ...]:
    return tuple(
        RefLabel(
            uri=uris[t],
            asset_id=f"keyframe_t{t:02d}",
            names=(),
            role="keyframe",
            t_s=float(t),
        )
        for t in times
    )


def _with_labels(base: Package, labels: tuple[RefLabel, ...]) -> RenderPackage:
    if isinstance(base, RenderPackage):
        return replace(base, reference_labels=labels)
    return to_render_package(base, labels, "", "", "")


def anchored_package(
    base: Package,
    inp: PlanInput,
    plan: KeyframePlan,
    uris: Sequence[str],
    max_images: int,
    state_refs: bool,
) -> Package:
    """D1 (`state_refs`) / D2 package: one Omni call anchored on the clip's keyframes."""
    last_t = len(uris) - 1
    times = anchor_times(last_t, max_images - 2 if state_refs else 3)
    labels = _keyframe_labels(uris, times) if state_refs else ()
    spec = parse_spec(base.spec_source)
    timeline = [] if state_refs else timeline_lines(plan, times)
    text = (
        render_anchored(spec, timeline, state_refs)
        if spec is not None
        else segment_prompt(inp, 0, last_t)
    )
    return replace(
        _with_labels(base, labels),
        compiled_prompt=text,
        spec_json="",
        first_frame_uri=uris[0],
        last_frame_uri=uris[last_t],
        source_video_uri=None,
        reference_asset_ids=[lbl.asset_id for lbl in labels],
        reference_uris=[lbl.uri for lbl in labels],
        duration_s=inp.duration_s,
    )
