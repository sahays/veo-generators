"""Structured keyframe checker: per-entity facts from a cheap VLM, judged deterministically.

The VLM only reports facts per listed entity (present, instance count, horizontal centre,
whether THAT character shows its own pose, whether the outfit matches) plus extra characters
and unexpected changes versus the previous keyframe. `compare` turns facts into short,
per-entity issues — one check per entity and aspect, never a scene-wide blob.
"""

from __future__ import annotations

import re
from typing import Final, Literal

from pydantic import BaseModel, Field

from ..plan.models import Keyframe

REGION_TOLERANCE: Final[float] = 0.25
POSE_WORDS: Final[int] = 14
_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^- \[(character|object)\] ([^|]+?)\s*(\||$)"
)


class EntitySeen(BaseModel):
    name: str
    present: bool
    count: int = 0
    x: float | None = Field(default=None, ge=0.0, le=1.0)
    pose_matches: bool = True
    outfit_matches: bool = True


class KeyframeCheck(BaseModel):
    """VLM answer schema for one keyframe."""

    entities: list[EntitySeen] = Field(default_factory=list)
    extra_characters: int = 0
    unexpected_changes: list[str] = Field(default_factory=list)

    @classmethod
    def mock_response(cls, prompt: str) -> KeyframeCheck:
        """Offline (MockVLMProvider) answer: every listed entity seen once, as planned."""
        return parse_expected(prompt)


EntityKind = Literal["character", "object"]


def short_pose(pose: str) -> str:
    words = pose.split()
    return " ".join(words[:POSE_WORDS]) + ("…" if len(words) > POSE_WORDS else "")


def check_prompt(frame: Keyframe, drawn: list[str], with_previous: bool = False) -> str:
    """Per-entity questions (one machine-readable line per entity)."""
    chars = [
        f"- [character] {c.name} | expected x={c.x:.2f} | own pose: {short_pose(c.pose)} | "
        f"outfit: {c.wardrobe[:80]}"
        for c in frame.characters
    ]
    objs = [f"- [object] {name}" for name in drawn]
    prev = (
        "\nThe FIRST image is the previous keyframe; inspect the LAST image. Planned changes: "
        f"{'; '.join(frame.delta) or 'none'}. In unexpected_changes list other visible "
        "differences (furniture moved/recoloured, door state, object vanished/duplicated)."
        if with_previous
        else ""
    )
    return (
        "Inspect the storyboard frame. For EVERY listed entity report: present, count (separate "
        "instances), x (horizontal centre 0=left..1=right, null if absent), and for characters "
        "pose_matches (does THIS character show its own pose; judge nobody else) and "
        "outfit_matches.\n"
        + "\n".join(chars + objs)
        + "\nextra_characters = people/creatures not listed."
        + prev
    )


def parse_expected(prompt: str) -> KeyframeCheck:
    """A passing check for exactly the entities a `check_prompt` lists."""
    names = [m.group(2) for line in prompt.splitlines() if (m := _LINE_RE.match(line))]
    return KeyframeCheck(
        entities=[EntitySeen(name=n, present=True, count=1) for n in names]
    )


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def _char_issues(
    c_name: str, x: float, pose: str, seen: EntitySeen | None
) -> list[str]:
    if seen is None or not seen.present:
        return [f"{c_name}: missing"]
    out = [f"{c_name}: appears {seen.count} times"] if seen.count > 1 else []
    if seen.x is not None and abs(seen.x - x) > REGION_TOLERANCE:
        out.append(f"{c_name}: at x={seen.x:.2f}, expected x={x:.2f}")
    if not seen.pose_matches:
        out.append(f"{c_name}: pose should be '{short_pose(pose)}'")
    if not seen.outfit_matches:
        out.append(f"{c_name}: outfit differs from reference")
    return out


def _object_issues(name: str, seen: EntitySeen | None) -> list[str]:
    if seen is None or not seen.present or seen.count == 0:
        return [f"{name}: missing"]
    return [f"{name}: appears {seen.count} times"] if seen.count > 1 else []


def compare(frame: Keyframe, check: KeyframeCheck, drawn: list[str]) -> list[str]:
    """Short per-entity issues (empty = keyframe matches its plan)."""
    seen = {_norm(e.name): e for e in check.entities}
    issues: list[str] = []
    for c in frame.characters:
        issues += _char_issues(c.name, c.x, c.pose, seen.get(_norm(c.name)))
    for name in drawn:
        issues += _object_issues(name, seen.get(_norm(name)))
    if check.extra_characters > 0:
        issues.append(f"remove {check.extra_characters} extra character(s)")
    return issues + [f"unexpected change: {c}"[:160] for c in check.unexpected_changes]
