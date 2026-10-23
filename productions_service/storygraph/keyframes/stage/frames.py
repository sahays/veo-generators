"""Conversions between rendered keyframes, stored `KeyframeFrame`s and plan state (pure)."""

from __future__ import annotations

from ...schemas.keyframes import KeyframeFrame, KeyframeFrameStatus
from ..plan.models import Keyframe
from ..render.renderer import RenderedKeyframe
from ..render.sink import StoredKeyframe


def frame_status(rk: RenderedKeyframe, max_retries: int) -> KeyframeFrameStatus:
    """approved (no issues) | manual_edit (issues after every retry) | needs_review."""
    if not rk.issues:
        return "approved"
    return "manual_edit" if rk.attempts > max_retries else "needs_review"


def state_summary(frame: Keyframe) -> str:
    """Who does what and holds what at this second (for the UI strip caption)."""
    names = {o.entity_id: o.name for o in frame.objects}
    parts = []
    for c in frame.characters:
        held = ", ".join(names.get(h, h) for h in c.holding)
        parts.append(
            f"{c.name}: {c.pose.rstrip('.')}" + (f" (holding {held})" if held else "")
        )
    return "; ".join(parts)


def to_frame(
    rk: RenderedKeyframe, plan_frame: Keyframe, max_retries: int, human: bool = False
) -> KeyframeFrame:
    return KeyframeFrame(
        t=rk.t,
        asset_id=rk.stored.asset_id,
        uri=rk.stored.uri,
        status="approved" if rk.shared_from else frame_status(rk, max_retries),
        attempts=rk.attempts,
        issues=list(rk.issues),
        shared_from=rk.shared_from,
        edited_by="human" if human else "pipeline",
        state_summary=state_summary(plan_frame),
        drift=dict(rk.metrics),
    )


def to_rendered(frame: KeyframeFrame, png: bytes = b"") -> RenderedKeyframe:
    """Stored frame -> renderer frame (PNG loaded lazily by callers that need pixels)."""
    return RenderedKeyframe(
        t=frame.t,
        png=png,
        stored=StoredKeyframe(frame.asset_id, frame.uri),
        attempts=frame.attempts,
        issues=tuple(frame.issues),
        reused=frame.shared_from is not None,
        shared_from=frame.shared_from,
        metrics=dict(frame.drift),
    )
