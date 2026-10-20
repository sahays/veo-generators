"""Clip-scoped spec regeneration for automatic repair of spec-caused QA failures.

Re-runs the SCREENWRITER for ONE clip (rewrite its `omni_prompt` / covered step actions
against the critic's spec-level defects, validated with the same screenplay clip rules
as manual edits) and the DIRECTOR mapping for that clip's shot only (current graph
state, props and look; camera/cast staging kept). Sibling clips and shots are untouched.

The shot's repair budget survives the content change: a spec regeneration *is* a repair
attempt, so `repair_attempts` is restored after the director's content-hash reset.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel, Field

from ...adapters.mock import MockLLMClient
from ...config import Config
from ...errors import ValidationFailed
from ...repair.clip_edit import ClipEdit, apply_clip_edit, load_shot_clip
from ...repo import Repo
from ...schema import ClipScript, Role, Scene, Shot
from ...shots import compute_shot_content_hash, find_scene_clip
from ...tools.registry import ToolContext
from ...tools.role_helpers import ShotDraft, normalize_indian_epic_names
from ...views import scene_view
from ..runner import run_role
from .director import build_scene_blocking, persist_clip_shot

logger = logging.getLogger(__name__)
_MAX_ACTION_WORDS: Final[int] = 48
_MAX_FEEDBACK: Final[int] = 8


class ClipRespecOutput(BaseModel):
    """Screenwriter rewrite of one clip (empty fields = keep as is)."""

    omni_prompt: str = ""
    step_actions: dict[int, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class ClipRespecResult:
    """Outcome of one clip-scoped spec regeneration."""

    shot_id: str
    prompt_rewritten: bool
    shot_remapped: bool
    prev_hash: str | None
    new_hash: str | None

    @property
    def changed(self) -> bool:
        return self.prev_hash != self.new_hash


def _log(
    what: str, why: str, how: str, repo: Repo, shot_id: str, **extra: object
) -> None:
    logger.info(
        what,
        extra={
            "who": "storygraph.agents.role.clip_respec",
            "where": f"clip_respec:{shot_id}",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": how,
            "project_id": repo.project_id,
            "shot_id": shot_id,
            **extra,
        },
    )


def _respec_prompt(scene: Scene, clip: ClipScript, feedback: list[str]) -> str:
    steps = [
        s.model_dump(mode="json")
        for s in scene.interaction_steps
        if s.step_index in clip.step_indices
    ]
    return (
        f"Rewrite ONLY clip {clip.clip_index} of scene '{scene.id}'. A video render of it failed QA "
        "because the SPEC (not the renderer) was wrong. Fix the spec so it can be rendered faithfully.\n"
        f"QA DEFECTS ATTRIBUTED TO THE SPEC: {json.dumps(feedback[:_MAX_FEEDBACK])}\n"
        "RULES: keep every dialogue line verbatim with its speaker; keep the clip's opening_state and "
        "closing_state; at most 2 key actions; speech before the last action; every object mentioned "
        "exists exactly once and starts where the opening_state says; no camera, lighting or timestamps; "
        "plain present tense. Return `omni_prompt` and optionally `step_actions` keyed by step_index "
        f"(only steps {clip.step_indices}).\n"
        f"CLIP: {clip.model_dump_json()}\nSTEPS: {json.dumps(steps)}"
    )


def _normalize_action(text: str) -> str:
    first_clause = normalize_indian_epic_names(text.split(";")[0])
    return " ".join(first_clause.split()[:_MAX_ACTION_WORDS])


def _as_edit(out: ClipRespecOutput, clip: ClipScript) -> ClipEdit | None:
    prompt = out.omni_prompt.strip()
    actions = {
        idx: _normalize_action(a)
        for idx, a in out.step_actions.items()
        if idx in clip.step_indices and a.strip()
    }
    new_prompt = prompt if prompt and prompt != clip.omni_prompt.strip() else None
    if new_prompt is None and not actions:
        return None
    return ClipEdit(omni_prompt=new_prompt, step_actions=actions or None)


def _rewrite_clip(
    ctx: ToolContext,
    scene: Scene,
    clip: ClipScript,
    feedback: list[str],
    mock_llm: MockLLMClient | None,
) -> bool:
    """Ask the screenwriter for a clip rewrite; persist it only if it passes clip rules."""
    res = run_role(
        role=Role.SCREENWRITER,
        ctx=ctx,
        user_prompt=_respec_prompt(scene, clip, feedback),
        output_schema=ClipRespecOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: ClipRespecOutput(),
    )
    edit = _as_edit(res.output, clip)
    if edit is None:
        return False
    try:
        apply_clip_edit(ctx.repo, scene, clip, edit)
    except ValidationFailed as vf:
        _log(
            "clip_respec_rejected",
            str(vf),
            "screenplay clip rules",
            ctx.repo,
            f"{scene.id}#{clip.clip_index}",
        )
        return False
    return True


def remap_clip_shot(ctx: ToolContext, shot: Shot) -> bool:
    """Re-run the director's clip->shot mapping for `shot` only (staging kept from the shot)."""
    sview = scene_view(ctx.repo, shot.scene_id)
    clips = sview.scene.clips
    pos = next(
        (i for i, c in enumerate(clips, 1) if c.clip_index == shot.clip_index), 0
    )
    if not pos or f"shot_{shot.scene_id}_{pos:02d}" != shot.id:
        return False  # not a director-mapped shot id; never mint a sibling shot
    blk, _, _ = build_scene_blocking(ctx, sview)
    blk.prev_positions = {c.entity_id: c.position for c in shot.cast}
    draft = ShotDraft(
        shot_id=shot.id,
        index_in_scene=shot.index_in_scene,
        story_order=shot.story_order,
        location_id=shot.location_id,
        cast=list(shot.cast),
        prop_ids=list(shot.prop_ids),
        camera=shot.camera,
        look=shot.look,
        clip_index=shot.clip_index,
    )
    persist_clip_shot(ctx, blk, pos, clips[pos - 1], draft)
    return True


def _restore_budget(repo: Repo, prev: Shot) -> Shot:
    """Re-hash the shot; keep its repair budget (regeneration is itself a repair attempt).

    Staleness is left as it was: readiness already requires an APPROVED run of the new
    hash, and a stale mark would make later repair passes re-render past the cap.
    """
    shot = repo.get_shot(prev.id) or prev
    scene = repo.get_scene(shot.scene_id)
    clip = find_scene_clip(scene.clips, shot.clip_index) if scene else None
    update: dict[str, object] = {
        "content_hash": compute_shot_content_hash(shot, clip),
        "repair_attempts": prev.repair_attempts,
        "needs_manual_edit": False,
        "manual_edit_reasons": [],
        "stale": prev.stale,
        "stale_reason": prev.stale_reason,
    }
    return repo.put_shot(shot.model_copy(update=update))


def respec_clip_for_shot(
    repo: Repo,
    cfg: Config,
    shot_id: str,
    feedback: list[str],
    mock_llm: MockLLMClient | None = None,
) -> ClipRespecResult:
    """Regenerate the spec of `shot_id`'s clip (screenwriter) and shot (director) only."""
    prev, scene, clip = load_shot_clip(repo, shot_id)
    sw_ctx = ToolContext(repo=repo, role=Role.SCREENWRITER, cfg=cfg)
    rewritten = _rewrite_clip(sw_ctx, scene, clip, feedback, mock_llm)
    remapped = remap_clip_shot(
        ToolContext(repo=repo, role=Role.DIRECTOR, cfg=cfg), prev
    )
    saved = _restore_budget(repo, prev)
    result = ClipRespecResult(
        shot_id, rewritten, remapped, prev.content_hash, saved.content_hash
    )
    _log(
        "clip_spec_regenerated",
        "; ".join(feedback[:_MAX_FEEDBACK]) or "spec-caused QA failure",
        f"screenwriter_rewrite={rewritten} director_remap={remapped} changed={result.changed}",
        repo,
        shot_id,
        prev_hash=prev.content_hash,
        new_hash=saved.content_hash,
        repair_attempts=saved.repair_attempts,
    )
    return result
