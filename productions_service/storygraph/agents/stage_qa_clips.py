"""Stage-QA auto-remediation for Omni clips: deterministically re-partition scenes whose clips break rules."""

from __future__ import annotations

import logging

from ..clips.builder import build_clips
from ..clips.limits import count_spoken_words
from ..clips.refs import dialogue_refs, entity_names, step_refs
from ..clips.validation import validate_scene_clips
from ..config import Config
from ..repo import Repo
from ..schema import Role
from ..tools import write_tools as wt
from ..tools.registry import ToolContext

logger = logging.getLogger(__name__)


def remediate_scene_clips(repo: Repo, cfg: Config, fixed: list[str]) -> None:
    """Rebuild clips for scenes with steps whose clip partition/limits are invalid."""
    ctx = ToolContext(repo=repo, role=Role.SCREENWRITER, cfg=cfg)
    names = entity_names(repo.list_entities())
    for sc in repo.list_scenes():
        if not sc.interaction_steps:
            continue
        lines = repo.list_dialogue(scene_id=sc.id)
        words = {d.id: count_spoken_words(d.text) for d in lines}
        steps = [s.step_index for s in sc.interaction_steps]
        issues = validate_scene_clips(sc.id, steps, sc.clips, words)
        if not issues:
            continue
        clips = build_clips(
            step_refs(sc.interaction_steps, names), dialogue_refs(lines, names)
        )
        wt.update_scene_script(
            ctx, scene_id=sc.id, summary=sc.summary, mood=sc.mood, clips=clips
        )
        fixed.append(f"Re-partitioned {sc.id} into {len(clips)} Omni clips.")
        logger.info(
            "Stage QA rebuilt scene Omni clips",
            extra={
                "who": "stage_qa",
                "where": "stage_qa_clips.remediate_scene_clips",
                "what": "rebuild_clips",
                "scene_id": sc.id,
                "clip_count": len(clips),
                "why": [i.code for i in issues],
                "how": "deterministic_balanced_partition",
            },
        )
