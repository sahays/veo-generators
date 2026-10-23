"""Keyframe ground truth for the clip critic and for keyframe-routed repair (pure + repo reads).

* `keyframe_refs`: the shot's approved first/last keyframes as labelled expected-state images,
  so the critic's object-count and wardrobe judgements compare against the clip's keyframes.
* `keyframe_defects`: QA defects that are state / prop / wardrobe problems (fixable by cheap
  keyframe image edits) as opposed to motion / action / camera / audio problems (re-render).
"""

from __future__ import annotations

from typing import Final

from ...repo import Repo
from ...repo.keyframe_sets import KeyframeSetRepo
from ...schema import QAReport

STATE_DEFECT_PREFIXES: Final[tuple[str, ...]] = (
    "extra_object",
    "missing_object",
    "object_state",
    "object_",
    "duplicate",
    "morphing",
    "wardrobe",
    "outfit",
    "identity",
    "continuity_break",
)


def is_state_defect(defect_type: str) -> bool:
    return defect_type.lower().startswith(STATE_DEFECT_PREFIXES)


def keyframe_defects(report: QAReport) -> list[str]:
    """Concise texts of the report's state/prop/wardrobe defects (empty = motion-only)."""
    return [
        f"{d.type} [{d.subject}]: {d.evidence}"[:200]
        for d in report.defects
        if is_state_defect(d.type)
    ]


def keyframe_refs(
    repo: Repo, shot_id: str, max_refs: int = 2
) -> list[tuple[int, bytes]]:
    """(t, png) of the shot's active keyframes used as expected state (first, last, ...)."""
    ks = KeyframeSetRepo(repo.store).active_for_shot(shot_id)
    if ks is None or ks.failure_reason or not ks.frames or max_refs <= 0:
        return []
    picks = [ks.frames[0], ks.frames[-1]][:max_refs]
    return [(f.t, repo.blobs.get_bytes(f.uri)) for f in picks]
