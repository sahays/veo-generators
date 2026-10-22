"""Deterministic S6 remediation for validation issues that need no LLM.

* V6  – clamp the shot duration into (0, max_duration_s];
* V7  – re-time action beats to be positive, ordered, non-overlapping and inside the shot;
* V9  – clear `speaking` on cast without an assigned line;
* cast_position_collision – move colliding foreground cast to a free left/center/right slot.
Each fix returns a human-readable record naming the shot and what changed.
"""

from __future__ import annotations

from typing import Final

from ..config import Config
from ..repo import Repo
from ..schema import ActionBeat, CastInShot, Shot
from ..validate import ValidationIssue

FIXABLE: Final[frozenset[str]] = frozenset(
    {"V6", "V7", "V9", "cast_position_collision"}
)
_SLOTS: Final[tuple[str, ...]] = ("left", "center", "right")
_MIN_BEAT_S: Final[float] = 0.1


def _retime(beats: list[ActionBeat], duration: float) -> list[ActionBeat]:
    """Evenly re-time beats in their order when any is out of range or overlapping."""
    if not beats:
        return beats
    span = max(duration, _MIN_BEAT_S * len(beats)) / len(beats)
    return [
        b.model_copy(
            update={
                "t_start_s": round(i * span, 3),
                "t_end_s": round((i + 1) * span, 3),
            }
        )
        for i, b in enumerate(beats)
    ]


def _free_positions(cast: list[CastInShot]) -> list[CastInShot]:
    taken: set[str] = set()
    out: list[CastInShot] = []
    for c in cast:
        if (
            c.framing == "background"
            or c.position not in _SLOTS
            or c.position not in taken
        ):
            taken.add(c.position)
            out.append(c)
            continue
        slot = next((s for s in _SLOTS if s not in taken), "background")
        taken.add(slot)
        out.append(c.model_copy(update={"position": slot}))
    return out


def _fix_shot(
    shot: Shot, codes: set[str], cfg: Config, repo: Repo
) -> tuple[Shot, list[str]]:
    update: dict[str, object] = {}
    notes: list[str] = []
    duration = shot.duration_s
    if "V6" in codes:
        duration = min(max(shot.duration_s, 1.0), cfg.video.max_duration_s)
        update["duration_s"] = duration
        notes.append(f"duration {shot.duration_s}s -> {duration}s")
    if "V7" in codes or "V6" in codes:
        update["beats"] = _retime(list(shot.beats), duration)
        notes.append(f"re-timed {len(shot.beats)} beats inside {duration}s")
    cast = list(shot.cast)
    if "V9" in codes:
        speakers = {
            d.speaker_id for did in shot.dialogue_ids if (d := repo.get_dialogue(did))
        }
        cast = [
            c.model_copy(update={"speaking": c.speaking and c.entity_id in speakers})
            for c in cast
        ]
        notes.append("cleared speaking on cast without a line")
    if "cast_position_collision" in codes:
        cast = _free_positions(cast)
        notes.append("moved colliding foreground cast to free slots")
    update["cast"] = cast
    return shot.model_copy(update=update), notes


def remediate_validation(
    repo: Repo, cfg: Config, issues: list[ValidationIssue]
) -> list[str]:
    """Apply deterministic fixes for fixable error codes; returns one record per shot."""
    codes_by_shot: dict[str, set[str]] = {}
    for i in issues:
        if i.severity == "error" and i.code in FIXABLE:
            codes_by_shot.setdefault(i.node_id, set()).add(i.code)
    applied: list[str] = []
    for shot_id, codes in codes_by_shot.items():
        shot = repo.get_shot(shot_id)
        if shot is None:
            continue
        fixed, notes = _fix_shot(shot, codes, cfg, repo)
        repo.put_shot(fixed)
        applied.append(f"{shot_id}: " + "; ".join(notes))
    return applied
