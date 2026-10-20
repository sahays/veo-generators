"""Spec-aware S9 critic prompt: rubric instructions + image manifest + compiled spec JSON.

The prompt deliberately carries NO attempt number and NO story events outside the compiled
spec, so every attempt is judged by the same rubric against this clip's own sequence only.
"""

from __future__ import annotations

from .rubric import rubric_keys_line
from .spec import CriticSpec


def reference_label(name: str, kind: str = "identity") -> str:
    """Label burned into (and listed for) a reference image."""
    return f"REFERENCE — {name} {kind}"


PREV_FRAME_LABEL = "PREVIOUS APPROVED CLIP — LAST FRAME"


def frame_label(t_s: float, is_last: bool = False) -> str:
    """Label burned into (and listed for) a sampled video frame."""
    return f"CLIP FRAME t={t_s:.2f}s" + (" (LAST)" if is_last else "")


def _manifest(labels: list[str]) -> str:
    """Numbered list describing every attached image in order."""
    return "\n".join(f"[{i}] {label}" for i, label in enumerate(labels, start=1))


def _step_lines(spec: CriticSpec) -> str:
    """Readable checklist of spec steps (the ONLY events to judge)."""
    if not spec.steps:
        return "(no explicit sequence; judge the actions described in CLIP_SPEC_JSON)"
    return "\n".join(
        f"{s.n}. {s.text}" + (f" -> end state: {s.end_state}" if s.end_state else "")
        for s in spec.steps
    )


def _object_lines(spec: CriticSpec) -> str:
    """Expected single-instance objects with start/end placement."""
    return (
        "\n".join(
            f"- {o.name}: start {o.start or 'in scene'}; end {o.end or o.start or 'unchanged'}"
            + ("" if o.in_frame else " (offscreen set dressing; not expected in view)")
            for o in spec.objects
        )
        or "(none)"
    )


def build_critic_prompt(
    shot_id: str,
    spec: CriticSpec,
    image_labels: list[str],
    has_prev_frame: bool,
    instructions: str,
) -> str:
    """Assemble the full critic prompt for one rendered clip."""
    cam = spec.camera
    return "\n".join(
        [
            instructions.strip(),
            f"shot_id={shot_id}",
            "ATTACHED IMAGES (in order; each image also carries its label as a banner):",
            _manifest(image_labels),
            "SPEC SEQUENCE (judge ONLY these steps; ignore any other story events):",
            _step_lines(spec),
            (
                "EXPECTED OBJECTS (each exactly one instance unless the spec says "
                "otherwise; set in_frame_expected=false when the framing excludes the "
                "object's location — out of frame is NOT missing):"
            ),
            _object_lines(spec),
            f"EXPECTED CAMERA: size={cam.size} angle={cam.angle} move={cam.move}",
            f"SPEAKERS WITH LINES: {', '.join(spec.speakers) or 'none'}",
            f"SINGLE CONTINUOUS TAKE: {'yes' if spec.single_take else 'no'}",
            f"CLIP_SPEC_JSON: {spec.raw_json}",
            rubric_keys_line(spec, has_prev_frame),
        ]
    )
