"""Cheap VLM keyframe check: structured counts compared against the plan (compare is pure)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..plan.models import Keyframe
from .prompts import visible_names


class ObjectCount(BaseModel):
    name: str
    count: int


class CharacterSeen(BaseModel):
    name: str
    present: bool
    outfit_matches: bool


class PoseSeen(BaseModel):
    name: str
    matches_pose: bool


class KeyframeCheck(BaseModel):
    """VLM answer schema for one keyframe."""

    objects: list[ObjectCount] = Field(default_factory=list)
    characters: list[CharacterSeen] = Field(default_factory=list)
    poses: list[PoseSeen] = Field(default_factory=list)
    extra_characters: int = 0
    unexpected_changes: list[str] = Field(default_factory=list)

    @classmethod
    def mock_response(cls, prompt: str) -> KeyframeCheck:
        """Offline (MockVLMProvider) answer: everything the prompt lists is seen as planned."""
        return parse_expected(prompt)


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def compare(frame: Keyframe, check: KeyframeCheck) -> list[str]:
    """Plan violations seen in the image (empty = keyframe matches its plan)."""
    counts = {_norm(o.name): o.count for o in check.objects}
    seen = {_norm(c.name): c for c in check.characters}
    issues: list[str] = []
    for name in visible_names(frame):
        n = counts.get(_norm(name), 0)
        if n != 1:
            issues.append(
                f"{name} must appear exactly once (seen {n})"
                if n
                else f"{name} is missing; it must be visible exactly once"
            )
    for char in frame.characters:
        got = seen.get(_norm(char.name))
        if got is None or not got.present:
            issues.append(f"{char.name} is missing")
        elif not got.outfit_matches:
            issues.append(f"{char.name} must wear exactly: {char.wardrobe}")
    poses = {_norm(p.name): p.matches_pose for p in check.poses}
    issues += [
        f"{c.name} (and nobody else) must be: {c.pose}"
        for c in frame.characters
        if not poses.get(_norm(c.name), True)
    ]
    issues += [
        f"unexpected change vs previous keyframe: {c}" for c in check.unexpected_changes
    ]
    if check.extra_characters > 0:
        issues.append(f"remove {check.extra_characters} extra character(s)")
    return issues


_SECTIONS = (("object", "objects"), ("outfit", "characters"), ("pose", "poses"))


def parse_expected(prompt: str) -> KeyframeCheck:
    """A passing `KeyframeCheck` for exactly the names listed in a `check_prompt`."""
    found: dict[str, list[str]] = {"objects": [], "characters": [], "poses": []}
    section = ""
    for line in prompt.splitlines():
        if line.startswith("For each"):
            section = next((key for word, key in _SECTIONS if word in line), "")
        elif line.startswith("- ") and section and line != "- (none)":
            found[section].append(line[2:].split(":")[0].strip())
    return KeyframeCheck(
        objects=[ObjectCount(name=n, count=1) for n in found["objects"]],
        characters=[
            CharacterSeen(name=n, present=True, outfit_matches=True)
            for n in found["characters"]
        ],
        poses=[PoseSeen(name=n, matches_pose=True) for n in found["poses"]],
    )
