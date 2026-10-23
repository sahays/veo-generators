"""Reuse rules for S8_KEYFRAMES: whole current sets, and the done prefix of a failed set.

* A shot's active set is CURRENT (reused, nothing regenerated) when it did not fail, matches
  the plan and the plate, and starts on the previous clip's last frame (`starts_on`).
* A FAILED set keeps the frames finished before the failure; when plan, plate and start
  frame still match, a resume continues at the first missing second (`resume_point`).
"""

from __future__ import annotations

from ...repo import Repo
from ...schemas.keyframes import KeyframeSet
from ..plan.models import KeyframePlan
from ..render.renderer import RenderedKeyframe
from .frames import to_rendered


def starts_on(ks: KeyframeSet, prev: KeyframeSet | None) -> bool:
    """Frame 0 is the previous clip's last frame (or owned, for the scene's first clip)."""
    if not ks.frames:
        return False
    if prev is None or not prev.frames:
        return ks.frames[0].shared_from is None
    return ks.frames[0].asset_id == prev.last.asset_id


def _matches(ks: KeyframeSet, plan: KeyframePlan, plate_asset_id: str | None) -> bool:
    if ks.plan_hash != plan.plan_hash:
        return False
    return plate_asset_id is None or ks.plate_asset_id == plate_asset_id


def is_current(
    active: KeyframeSet | None,
    plan: KeyframePlan,
    prev: KeyframeSet | None,
    plate_asset_id: str | None = None,
) -> bool:
    """Reuse `active` only if it succeeded, plan + plate are unchanged and it chains on."""
    if active is None or active.failure_reason:
        return False
    return _matches(active, plan, plate_asset_id) and starts_on(active, prev)


def resume_point(
    active: KeyframeSet | None,
    plan: KeyframePlan,
    prev: KeyframeSet | None,
    plate_asset_id: str | None,
) -> int:
    """How many leading frames of a failed set are kept (0 = derive the shot afresh)."""
    if active is None or not active.failure_reason or not active.frames:
        return 0
    if not _matches(active, plan, plate_asset_id) or not starts_on(active, prev):
        return 0
    return min(len(active.frames), len(plan.keyframes) - 1)


def prior_frames(repo: Repo, ks: KeyframeSet, t: int) -> tuple[RenderedKeyframe, ...]:
    """Kept frames < t; only frame t-1 needs pixels (pose reference for frame t)."""
    out = [to_rendered(f) for f in ks.frames[:t]]
    if out:
        last = ks.frames[t - 1]
        out[-1] = to_rendered(last, repo.blobs.get_bytes(last.uri))
    return tuple(out)
