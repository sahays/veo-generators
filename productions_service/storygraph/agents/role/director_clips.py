"""Director clip→shot mapping: exactly one Shot per screenwriter ClipScript."""

from __future__ import annotations

import re
from typing import Final

from ...schema import ActionBeat, CameraSpec, CastInShot, ClipScript, InteractionStep
from ...tools.role_helpers import ShotDraft, normalize_indian_epic_names

_TEAR_RE: Final[re.Pattern[str]] = re.compile(
    r"tearful\s+starlight\s+sparkles?", re.IGNORECASE
)
_FALLBACK_CAMERAS: Final[tuple[CameraSpec, ...]] = (
    CameraSpec(shot_size="WS", angle="eye", movement="dolly_in", lens_mm=35),
    CameraSpec(shot_size="MCU", angle="eye", movement="static", lens_mm=50),
    CameraSpec(shot_size="CU", angle="low", movement="track", lens_mm=85),
)


def match_drafts_to_clips(
    drafts: list[ShotDraft], clips: list[ClipScript]
) -> list[ShotDraft | None]:
    """Align director drafts to clips by `clip_index`, then fill unmatched clips in draft order."""
    slot_of = {c.clip_index: pos for pos, c in enumerate(clips)}
    aligned: list[ShotDraft | None] = [None] * len(clips)
    leftovers: list[ShotDraft] = []
    for d in drafts:
        pos = slot_of.get(d.clip_index) if d.clip_index is not None else None
        if pos is not None and aligned[pos] is None:
            aligned[pos] = d
        else:
            leftovers.append(d)
    spare = iter(leftovers)
    return [a if a is not None else next(spare, None) for a in aligned]


def beats_for_clip(
    clip: ClipScript, steps: dict[int, InteractionStep], subject_ids: list[str]
) -> list[ActionBeat]:
    """Derive internal ActionBeats (one per covered step) evenly spanning the clip.

    Beat timings stay internal for validation/QA; the compiler sends `omni_prompt` to Omni instead.
    """
    covered = [steps[i] for i in clip.step_indices if i in steps]
    if not covered:
        return [
            ActionBeat(
                t_start_s=0.0,
                t_end_s=clip.duration_s,
                description=clip.omni_prompt,
                subject_ids=subject_ids,
            )
        ]
    span = round(clip.duration_s / len(covered), 2)
    beats: list[ActionBeat] = []
    for pos, st in enumerate(covered):
        t_end = (
            clip.duration_s if pos == len(covered) - 1 else round((pos + 1) * span, 2)
        )
        beats.append(
            ActionBeat(
                t_start_s=round(pos * span, 2),
                t_end_s=t_end,
                description=_TEAR_RE.sub(
                    "subtle glistening tears", normalize_indian_epic_names(st.action)
                ),
                subject_ids=[
                    sid for sid in (st.actor_id, st.target_id) if sid in subject_ids
                ]
                or subject_ids,
                pre_state=st.pre_state,
                post_state=st.post_state,
            )
        )
    return beats


def fallback_drafts(
    scene_id: str, location_id: str, lead_id: str, clips: list[ClipScript]
) -> list[ShotDraft]:
    """Deterministic one-draft-per-clip camera blocking used when the LLM is unavailable."""
    return [
        ShotDraft(
            shot_id=f"shot_{scene_id}_{c.clip_index:02d}",
            index_in_scene=pos,
            story_order=0,
            clip_index=c.clip_index,
            duration_s=c.duration_s,
            location_id=location_id,
            cast=[CastInShot(entity_id=lead_id, position="center", framing="MCU")],
            camera=_FALLBACK_CAMERAS[(pos - 1) % len(_FALLBACK_CAMERAS)].model_copy(
                update={"focus_target_id": lead_id}
            ),
        )
        for pos, c in enumerate(clips, start=1)
    ]
