"""Restyle prompts for the previz variants (pure).

* E1 (`<VIDEO_0>` restyle): Omni keeps the previz motion/camera/layout and only replaces the
  greybox with the referenced characters, props and set. Simple edit prompts work best for
  Omni video edits, so the text is short: style, colour mapping, keep-rules, dialogue.
* E2 (per-second frame restyle): the image model repaints one previz frame (composition) with
  the reference board (appearance), keeping every position, pose and the camera.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from ...keyframes.animate.anchored import dialogue_lines
from ...omni.phrasing import Names
from ...omni.spec import OmniClipSpec
from .mapping import Mapped, mapping_lines

KEEP_VIDEO: Final[str] = (
    "Keep ALL motion, timing, positions, poses, the camera move and the room layout exactly "
    "as in the source video; every object appears exactly once; no cuts, no on-screen text."
)
KEEP_FRAME: Final[str] = (
    "Keep the exact composition, camera, perspective, every position, pose and facing of "
    "Image 1; change only appearance. One still frame, no text, nobody who is not listed."
)


def _style(spec: OmniClipSpec | None, fallback: str) -> str:
    style = (spec.clip.style if spec is not None else None) or fallback
    return style or "the film's animated style"


EDIT_RULES: Final[str] = (
    "This is an EDIT of Video1, not a new video: keep every frame's camera position and "
    "move, the room, walls, floor, furniture and their positions pixel-aligned with Video1, "
    "and every character's path, timing and pose. Do not add, remove, move or resize "
    "anything; do not change the framing; one continuous take."
)


def e1_prompt(spec: OmniClipSpec | None, mapped: Sequence[Mapped], style: str) -> str:
    """`<VIDEO_0>` edit instruction (identity sheets stay bound as IMAGE_REF_k)."""
    names = Names.of(spec) if spec is not None else None
    talk = (
        dialogue_lines(spec, Names(name=names.name, tag={})) if spec and names else []
    )
    return "\n".join(
        [
            f"Edit <VIDEO_0> (a previz of this exact room) into {_style(spec, style)}: "
            "replace ONLY the coloured mannequins and coloured props with the referenced "
            "characters and objects by colour mapping, and refine surfaces where needed.",
            "COLOUR MAPPING:",
            *mapping_lines(list(mapped)),
            EDIT_RULES,
            KEEP_VIDEO,
            "Use the reference images for identity, outfits and materials only.",
            *talk,
        ]
    )


def e2_frame_prompt(
    t: int,
    mapped: Sequence[Mapped],
    board_labels: Sequence[str],
    style: str,
    location: str = "",
) -> str:
    """Image-model restyle of previz frame `t` (Image 1) with the ref board (Image 2)."""
    board = (
        f"Image 2 is a labelled reference board ({', '.join(board_labels)}): appearance only."
        if board_labels
        else ""
    )
    room = (
        f"The plain greybox walls, floor and backdrop are the {location}: repaint them with "
        f'the materials, colours, window, door and details of its board tile "{location}".'
        if location
        else "Repaint the plain greybox walls and floor as a finished, detailed room."
    )
    lines = [
        f"Image 1 is second {t} of a greybox previz. Repaint it as a finished frame in {style}.",
        board,
        room,
        "COLOUR MAPPING (greybox element -> what to draw):",
        *mapping_lines(list(mapped)),
        KEEP_FRAME,
    ]
    return "\n".join(line for line in lines if line)
