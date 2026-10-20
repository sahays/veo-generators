"""Shot-size choice within Omni's camera limits (`FramingPolicy`).

A tight size (ECU/CU) is honoured only when the clip is one in-place action on one subject;
otherwise the camera renders at the policy default and the tight size is kept as a framing
intent. Used by the director (authoring), the spec linter and S7 remediation alike.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..clips.limits import FRAMING, FramingPolicy
from ..schema import CameraSpec, InteractionStep, ShotLook
from .locomotion import step_locomotion


@dataclass(frozen=True)
class FramingDecision:
    """Typed contract: the camera to render and the framing intent kept from a tight request."""

    camera: CameraSpec
    intent: str = ""

    @property
    def widened(self) -> bool:
        return bool(self.intent)


def tight_allowed(
    steps: Sequence[InteractionStep],
    character_ids: Iterable[str],
    policy: FramingPolicy = FRAMING,
) -> bool:
    """True for at most `tight_max_steps` in-place steps that involve a single character."""
    if len(steps) > policy.tight_max_steps:
        return False
    if any(step_locomotion(s) for s in steps):
        return False
    chars = frozenset(character_ids)
    involved = {s.actor_id for s in steps} | {
        s.target_id for s in steps if s.target_id in chars
    }
    return len(involved) <= 1


def plan_framing(
    camera: CameraSpec,
    steps: Sequence[InteractionStep],
    character_ids: Iterable[str],
    policy: FramingPolicy = FRAMING,
) -> FramingDecision:
    """Keep an allowed size; widen a disallowed tight size to the default (intent kept)."""
    if camera.shot_size not in policy.tight_sizes or tight_allowed(
        steps, character_ids, policy
    ):
        return FramingDecision(camera)
    wide = camera.model_copy(update={"shot_size": policy.default_size})
    return FramingDecision(wide, f"framing intent {camera.shot_size} on the focus")


def with_intent(look: ShotLook | None, intent: str) -> ShotLook | None:
    """Append the framing intent to the look's camera intent (idempotent)."""
    if not intent or look is None or intent in look.camera_motion_intent:
        return look
    joined = "; ".join(p for p in (look.camera_motion_intent.strip(), intent) if p)
    return look.model_copy(update={"camera_motion_intent": joined})
