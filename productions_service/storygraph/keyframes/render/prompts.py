"""Generation prompts: the locked scene plate and plate-anchored keyframes (pure).

Every keyframe is generated at constant depth from the same inputs — the scene plate, a
labelled reference board and (optionally) the previous keyframe as a pose/position-only
reference — never as an edit of an edit, so quality cannot compound over seconds or clips.
Every present character and drawn prop is enumerated with its board tile and screen region.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..plan.models import CharacterKey, Keyframe, ObjectKey, PlanInput
from ..plate.spec import PlateSpec

RULES = (
    "Rules: one still frame, no text or captions, nobody who is not listed. Every listed "
    "character and object appears exactly ONCE. Characters keep the exact face, body and "
    "outfit of their reference tile."
)


def region_words(x: float) -> str:
    third = "left third" if x < 1 / 3 else "right third" if x > 2 / 3 else "centre"
    return f"x={x:.2f} of the frame width ({third})"


def plate_prompt(
    spec: PlateSpec, has_location_ref: bool, board_labels: Sequence[str]
) -> str:
    pieces = ", ".join(o.name for o in spec.set_pieces) or "none beyond the room itself"
    lines = [
        "Create the EMPTY-SET MASTER PLATE of one scene of an animated film: the room only, "
        "with no people, creatures or loose props.",
        "Image 1 is the location sheet: match its architecture, materials and colours exactly."
        if has_location_ref
        else "",
        f"Image 2 is a labelled reference board of the furniture ({', '.join(board_labels)})."
        if board_labels
        else "",
        f"Location: {spec.location_name}{', ' + spec.time_of_day if spec.time_of_day else ''}. "
        f"{spec.location_description[:300]}",
        f"Furniture and fixtures to place (each exactly once, clearly visible): {pieces}.",
        "Camera: wide establishing shot at eye level, static, the whole set in view, leaving "
        "open floor in the left, centre and right thirds where characters will stand.",
        f"Style: {spec.style}." if spec.style else "",
        "Correct, natural colours and even lighting; no text.",
    ]
    return "\n".join(line for line in lines if line)


def _char_line(c: CharacterKey, names: dict[str, str]) -> str:
    held = ", ".join(names.get(h, h) for h in c.holding) or "nothing"
    return (
        f'- {c.name} (board tile "{c.name}"): at {region_words(c.x)}; wearing {c.wardrobe}; '
        f"pose: {c.pose}; holding: {held}."
    )


def drawn_props(frame: Keyframe, set_pieces: set[str]) -> list[ObjectKey]:
    """Visible, in-frame objects that are not already part of the plate."""
    return [
        o
        for o in frame.objects
        if o.visible and o.in_frame and o.entity_id not in set_pieces
    ]


def _prop_line(o: ObjectKey, on_board: set[str]) -> str:
    tile = f' (board tile "{o.name}")' if o.name in on_board else ""
    where = f"; at {region_words(o.x)}" if o.x is not None else ""
    return f"- {o.name}{tile}: {o.placement}{where}."


def _image_lines(board_labels: Sequence[str], has_prev: bool) -> list[str]:
    """Image roles in send order: plate, [board], [previous second]."""
    lines = [
        "Image 1 is the LOCKED SCENE PLATE: reproduce it exactly — same camera, framing, "
        "room, furniture positions, colours and lighting. Do not move, recolour, add or "
        "remove anything already in it."
    ]
    if board_labels:
        lines.append(
            f"Image {len(lines) + 1} is a labelled reference board "
            f"({', '.join(board_labels)}): appearance only."
        )
    if has_prev:
        lines.append(
            f"Image {len(lines) + 1} is the previous second: use it ONLY to keep each "
            "character's pose and position continuous; ignore its colours, grain and "
            "background."
        )
    return lines


def frame_prompt(
    inp: PlanInput,
    frame: Keyframe,
    set_pieces: set[str],
    board_labels: Sequence[str],
    has_prev: bool,
) -> str:
    names = {c.entity_id: c.name for c in inp.cast} | {
        o.entity_id: o.name for o in inp.objects
    }
    on_board = set(board_labels)
    props = drawn_props(frame, set_pieces)
    fixed = [o.name for o in frame.objects if o.entity_id in set_pieces and o.visible]
    hidden = [o.name for o in frame.objects if not o.visible]
    lines = [
        *_image_lines(board_labels, has_prev),
        f"Moment t={frame.t}s. Add exactly these characters (nobody else):"
        if frame.characters
        else f"Moment t={frame.t}s. No characters in this frame.",
        *[_char_line(c, names) for c in frame.characters],
        "Props to draw (each exactly once):" if props else "",
        *[_prop_line(o, on_board) for o in props],
        f"Already in the plate (keep exactly, each once): {', '.join(fixed)}."
        if fixed
        else "",
        f"Out of sight (do not draw): {', '.join(hidden)}." if hidden else "",
        RULES,
    ]
    return "\n".join(line for line in lines if line)


def board_entries(
    inp: PlanInput, frame: Keyframe, set_pieces: set[str]
) -> list[tuple[str, str]]:
    """(label, ref uri) for every present character and every drawn prop with a sheet."""
    chars = {c.entity_id for c in frame.characters}
    props = {o.entity_id for o in drawn_props(frame, set_pieces)}
    out = [(c.name, c.ref_uri) for c in inp.cast if c.entity_id in chars and c.ref_uri]
    out += [
        (o.name, o.ref_uri) for o in inp.objects if o.entity_id in props and o.ref_uri
    ]
    return out


def retry_suffix(issues: Sequence[str]) -> str:
    if not issues:
        return ""
    return (
        "\nThe previous attempt was wrong. Fix exactly these problems:\n"
        + "\n".join(f"- {i}" for i in issues)
    )
