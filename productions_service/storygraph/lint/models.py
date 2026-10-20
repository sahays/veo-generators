"""Typed contracts for the spec linter: `LintIssue` (output) and `LintCase` (input)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from ..clips.models import ClipScript
from ..omni.spec import OmniClipSpec
from ..schema import InteractionStep
from ..timeline.clip_context import ClipContext
from ..views import ShotView

LintRoute = Literal["S2", "S4"]
LintSeverity = Literal["error", "warn"]
_ROUTE_PREFIX: dict[str, str] = {"S2": "S2_CLIP_LINT", "S4": "S4_LINT"}
CODE_CAMERA: Final[str] = f"{_ROUTE_PREFIX['S4']}_CAMERA_MOVEMENT"
CODE_TOO_MANY_ACTIONS: Final[str] = f"{_ROUTE_PREFIX['S2']}_TOO_MANY_ACTIONS"
CODE_TOO_MANY_WORDS: Final[str] = f"{_ROUTE_PREFIX['S2']}_TOO_MANY_WORDS"


@dataclass(frozen=True)
class LintIssue:
    """One spec defect, routed to the authoring stage that must fix it.

    `code` carries the stage prefix (`S2_CLIP_LINT_*` re-runs screenplay + shots,
    `S4_LINT_*` re-runs the director) so `stages_to_redo_for_issues` can route it.
    """

    code: str
    shot_id: str
    message: str
    route: LintRoute
    severity: LintSeverity = "error"

    @property
    def node_id(self) -> str:
        return self.shot_id


def issue(
    name: str,
    shot_id: str,
    message: str,
    route: LintRoute,
    severity: LintSeverity = "error",
) -> LintIssue:
    """Build a `LintIssue` whose code is prefixed for stage routing."""
    return LintIssue(
        f"{_ROUTE_PREFIX[route]}_{name}", shot_id, message, route, severity
    )


@dataclass(frozen=True)
class LintCase:
    """Everything one clip's lint needs: its compiled spec, view, clip context and the
    previous clip's spec in the same scene (None for the first clip)."""

    spec: OmniClipSpec
    view: ShotView
    ctx: ClipContext
    clip: ClipScript | None
    steps: tuple[InteractionStep, ...]
    prev_spec: OmniClipSpec | None = None

    @property
    def shot_id(self) -> str:
        return self.view.shot.id


def blocking(issues: list[LintIssue]) -> list[LintIssue]:
    return [i for i in issues if i.severity == "error"]
