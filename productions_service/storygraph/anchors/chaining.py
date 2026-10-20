"""First-frame chaining policy: reuse the previous shot's last frame only from APPROVED runs.

Rules (review Theme 3 / item 6 of Theme 2):
- The predecessor is the previous shot in the scene, or the last shot of the previous scene.
- Chaining applies when `shot.continue_from_last_frame` is set, or the predecessor is shot in
  the same location (same-place continuation, within a scene or across a scene cut).
- The predecessor's *latest* run must be APPROVED, carry an extracted last frame, and the
  predecessor must not be stale. Frames from failed/superseded runs are never reused; when the
  predecessor is not approved the first frame is dropped and continuity relies on the
  clip's `opening_state` text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from ..repo import Repo
from ..schema import Asset, GenerationRun, Shot, Status

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChainDecision:
    """Outcome of the chaining policy for one shot (frame is None when not chained)."""

    frame: Asset | None
    predecessor_id: str | None
    reason: str


def _previous_scene_tail(repo: Repo, scene_id: str) -> Shot | None:
    scenes = repo.list_scenes()
    idx = next((i for i, sc in enumerate(scenes) if sc.id == scene_id), 0)
    if idx == 0:
        return None
    prev_shots = repo.list_shots(scene_id=scenes[idx - 1].id)
    return max(prev_shots, key=lambda s: s.index_in_scene, default=None)


def predecessor_shot(repo: Repo, shot: Shot) -> Shot | None:
    """Shot played immediately before `shot` (previous in scene, else previous scene's tail)."""
    earlier = [
        s
        for s in repo.list_shots(scene_id=shot.scene_id)
        if s.index_in_scene < shot.index_in_scene
    ]
    if earlier:
        return max(earlier, key=lambda s: s.index_in_scene)
    return _previous_scene_tail(repo, shot.scene_id)


def latest_run(repo: Repo, shot_id: str) -> GenerationRun | None:
    """Most recent render of `shot_id` (by creation time, then attempt)."""
    runs = repo.list_generation_runs(shot_id=shot_id)
    return max(runs, key=lambda r: (r.created_at, r.attempt), default=None)


def is_continuation(shot: Shot, prev: Shot) -> bool:
    """Explicit continuation flag, or same-place continuation (same location)."""
    return shot.continue_from_last_frame or prev.location_id == shot.location_id


def _approved_frame(repo: Repo, prev: Shot) -> tuple[Asset | None, str]:
    if prev.stale:
        return None, "predecessor_stale"
    run = latest_run(repo, prev.id)
    if run is None or run.status != Status.APPROVED:
        return None, "predecessor_latest_run_not_approved"
    if not run.extracted_last_frame_asset_id:
        return None, "approved_run_has_no_last_frame"
    frame = repo.get_asset(run.extracted_last_frame_asset_id)
    return frame, ("chained" if frame else "last_frame_asset_missing")


def decide_chain_frame(repo: Repo, shot: Shot) -> ChainDecision:
    """Apply the chaining policy and log the decision (who/where/what/when/why/how)."""
    prev = predecessor_shot(repo, shot)
    if prev is None:
        decision = ChainDecision(None, None, "no_predecessor")
    elif not is_continuation(shot, prev):
        decision = ChainDecision(None, prev.id, "not_a_continuation")
    else:
        frame, reason = _approved_frame(repo, prev)
        decision = ChainDecision(frame, prev.id, reason)
    _log.info(
        "first_frame_chain_decision",
        extra={
            "who": "storygraph.anchors.chaining",
            "where": f"decide_chain_frame:{shot.id}",
            "what": "chained" if decision.frame else "first_frame_dropped",
            "when": datetime.now(UTC).isoformat(),
            "why": decision.reason,
            "how": f"predecessor={decision.predecessor_id}",
        },
    )
    return decision


def resolve_chain_frame(repo: Repo, shot: Shot) -> Asset | None:
    """First-frame asset for `shot` under the approved-only chaining policy (or None)."""
    return decide_chain_frame(repo, shot).frame
