"""Prompt text for keyframe generation, per-second edits and the VLM keyframe check (pure)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..plan.models import CharacterKey, Keyframe, ObjectKey, PlanInput

_RULES = (
    "Rules: a single still frame, no text or captions, no extra characters. Each listed "
    "object appears exactly ONCE (never duplicate furniture or props). Characters keep the "
    "exact face, body and outfit of their identity sheets."
)


@dataclass(frozen=True)
class RefImage:
    """One reference image sent to the image model, with its caption."""

    uri: str
    caption: str


def _names(inp: PlanInput) -> dict[str, str]:
    return {c.entity_id: c.name for c in inp.cast} | {
        o.entity_id: o.name for o in inp.objects
    }


def _char_line(c: CharacterKey, names: dict[str, str]) -> str:
    held = ", ".join(names.get(h, h) for h in c.holding) or "nothing"
    return f"- {c.name} ({c.position} of frame), wearing {c.wardrobe}: {c.pose}. Holding: {held}."


def _object_lines(objects: Sequence[ObjectKey]) -> list[str]:
    shown = [f"- {o.name}: {o.placement}" for o in objects if o.visible and o.in_frame]
    hidden = [o.name for o in objects if not o.visible]
    tail = (
        [f"Present but out of sight (do not draw): {', '.join(hidden)}."]
        if hidden
        else []
    )
    return shown + tail


def visible_names(frame: Keyframe) -> list[str]:
    return [o.name for o in frame.objects if o.visible and o.in_frame]


def reference_images(inp: PlanInput, frame: Keyframe, budget: int) -> list[RefImage]:
    """Identity sheets (characters first), then the location plate, then focus props."""
    shown = {o.entity_id for o in frame.objects if o.visible and o.in_frame}
    refs = [
        RefImage(c.ref_uri, f"{c.name} identity sheet") for c in inp.cast if c.ref_uri
    ]
    if inp.location_ref_uri:
        refs.append(
            RefImage(inp.location_ref_uri, f"{inp.location_name} location plate")
        )
    refs += [
        RefImage(o.ref_uri, f"{o.name} prop sheet")
        for o in inp.objects
        if o.ref_uri and o.focus and o.entity_id in shown
    ]
    return refs[:budget]


def _captions(refs: Sequence[RefImage], offset: int = 1) -> str:
    return "\n".join(f"Image {i + offset}: {r.caption}." for i, r in enumerate(refs))


def frame_description(inp: PlanInput, frame: Keyframe) -> str:
    """Full visual state of `frame` (setting, camera, characters, objects)."""
    names = _names(inp)
    lines = [
        f"Style: {inp.style}." if inp.style else "",
        f"Setting: {frame.setting}. {inp.location_description[:400]}",
        f"Camera: {frame.camera.framing}.",
        "Characters (each exactly once):",
        *[_char_line(c, names) for c in frame.characters],
        "Objects in frame (each exactly once):",
        *_object_lines(frame.objects),
    ]
    return "\n".join(line for line in lines if line)


def initial_prompt(inp: PlanInput, frame: Keyframe, refs: Sequence[RefImage]) -> str:
    return "\n".join(
        [
            "Create the opening storyboard keyframe (t=0s) of an animated film shot.",
            frame_description(inp, frame),
            "Reference images (appearance only):",
            _captions(refs),
            _RULES,
        ]
    )


def edit_prompt(frame: Keyframe, refs: Sequence[RefImage]) -> str:
    """Edit the previous keyframe (Image 1) by exactly this second's delta."""
    keep = ", ".join(visible_names(frame))
    lines = [
        f"Edit Image 1 (the keyframe one second earlier) into the keyframe at t={frame.t}s.",
        "Change ONLY the following:",
        *[f"- {d}" for d in frame.delta],
        (
            "Keep everything else exactly the same: same characters, same outfits, same "
            "camera framing, same room layout, same objects in the same places, and the exact "
            "colours, lighting, saturation and sharpness of Image 1."
        ),
        *[
            f"{c.name} keeps the same pose and place."
            for c in frame.characters
            if not any(d.startswith(f"{c.name}") for d in frame.delta)
        ],
        f"Each of these objects appears exactly once: {keep}." if keep else "",
        _captions(refs, offset=2),
        _RULES,
    ]
    return "\n".join(line for line in lines if line)


def retry_suffix(issues: Sequence[str]) -> str:
    if not issues:
        return ""
    return (
        "\nThe previous attempt was wrong. Fix exactly these problems:\n"
        + "\n".join(f"- {i}" for i in issues)
    )


def check_prompt(frame: Keyframe, with_previous: bool = False) -> str:
    """Instructions for the cheap VLM keyframe check (structured output).

    With `with_previous` the first image is the previous keyframe and the LAST image is the
    one to inspect; the VLM also lists changes beyond this second's planned delta."""
    objs = "\n".join(f"- {n}" for n in visible_names(frame)) or "- (none)"
    chars = "\n".join(f"- {c.name}: wearing {c.wardrobe}" for c in frame.characters)
    poses = "\n".join(f"- {c.name}: {c.pose}" for c in frame.characters)
    return (
        "Inspect this storyboard frame carefully and count precisely.\n"
        f"For each object, report how many separate instances are visible (0 if none):\n{objs}\n"
        f"For each character, report whether present and whether the outfit matches:\n{chars}\n"
        "For each character, matches_pose = is THAT character (not someone else) shown "
        f"in this pose/action:\n{poses}\n"
        "Report extra_characters = number of people/creatures not listed above."
        + (
            _PREVIOUS_CHECK.format(delta="; ".join(frame.delta) or "nothing")
            if with_previous
            else ""
        )
    )


_PREVIOUS_CHECK = (
    "\nThe FIRST image is the previous keyframe (one second earlier); inspect the LAST image. "
    "Only these changes were planned: {delta}. List in unexpected_changes every other visible "
    "difference (a character's face/outfit/position, an object appearing, vanishing, moving or "
    "duplicating, camera or room layout changes). Empty list if none."
)
