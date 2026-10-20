"""Blocking spec linter: lint every compiled `OmniClipSpec` + shot view before S8 renders.

Issues route back to the screenwriter (`S2`) or director (`S4`); S7 raises
`ValidationFailed` on errors so no render money is spent on an invalid spec.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..budget import select_references
from ..compile import Package, compile_shot
from ..config import Config
from ..omni.spec import OmniClipSpec
from ..repo import Repo
from ..schema import Shot
from ..timeline.clip_context import clip_context, clip_steps_of
from ..views import shot_view
from .models import LintCase, LintIssue, blocking
from .rules import RULES

_log = logging.getLogger(__name__)


def lint_spec(case: LintCase) -> list[LintIssue]:
    """Run every rule on one clip."""
    return [i for rule in RULES for i in rule(case)]


def _case(
    repo: Repo, shot: Shot, spec: OmniClipSpec, prev: OmniClipSpec | None
) -> LintCase:
    view = shot_view(repo, shot.id)
    ctx = clip_context(repo, view.scene, shot)
    clip = next((c for c in view.scene.clips if c.clip_index == shot.clip_index), None)
    steps = clip_steps_of(view.scene, clip) if clip else ()
    return LintCase(spec, view, ctx, clip, steps, prev)


def _scene_order(shots: list[Shot]) -> list[Shot]:
    return sorted(shots, key=lambda s: (s.scene_id, s.index_in_scene))


def _log_lint(where: str, issues: list[LintIssue], n_shots: int) -> None:
    errors = blocking(issues)
    _log.info(
        "spec_lint_done",
        extra={
            "who": "storygraph.lint",
            "where": where,
            "what": f"{len(errors)} blocking / {len(issues)} total lint issues",
            "when": datetime.now(UTC).isoformat(),
            "why": "pre-render spec validation (S7)",
            "how": f"{len(RULES)} rules over {n_shots} compiled specs",
        },
    )


def lint_packages(repo: Repo, packages: dict[str, Package]) -> list[LintIssue]:
    """Lint every compiled package; each clip is compared with the previous clip of its scene."""
    out: list[LintIssue] = []
    prev_scene, prev_spec = "", None
    shots = _scene_order([s for s in repo.list_shots() if s.id in packages])
    for shot in shots:
        spec = OmniClipSpec.model_validate_json(packages[shot.id].compiled_prompt)
        prev = prev_spec if shot.scene_id == prev_scene else None
        out += lint_spec(_case(repo, shot, spec, prev))
        prev_scene, prev_spec = shot.scene_id, spec
    _log_lint("lint_packages", out, len(shots))
    return out


def _compile_spec(repo: Repo, cfg: Config, shot: Shot) -> OmniClipSpec:
    view = shot_view(repo, shot.id)
    plan = select_references(view, cfg, caps=cfg.video, repo=repo)
    pkg = compile_shot(view, plan, cfg, caps=cfg.video, project_id=repo.project_id)
    return OmniClipSpec.model_validate_json(pkg.compiled_prompt)


def lint_shot(repo: Repo, cfg: Config, shot_id: str) -> list[LintIssue]:
    """Compile and lint one shot (plus its in-scene predecessor) — used by the repair agent."""
    shot = repo.get_shot(shot_id)
    if shot is None:
        return []
    scene_shots = _scene_order(repo.list_shots(scene_id=shot.scene_id))
    before = [s for s in scene_shots if s.index_in_scene < shot.index_in_scene]
    prev = _compile_spec(repo, cfg, before[-1]) if before else None
    issues = lint_spec(_case(repo, shot, _compile_spec(repo, cfg, shot), prev))
    _log_lint(f"lint_shot:{shot_id}", issues, 1)
    return issues
