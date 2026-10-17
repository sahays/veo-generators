"""MUSIC_DIRECTOR role agent runner (`music_director_agent`)."""

from __future__ import annotations

from ...adapters.mock import MockLLMClient
from ...schema import Role, Scene, Shot
from ...tools import write_tools as wt
from ...tools.registry import ToolContext
from ...tools.role_helpers import (
    MusicCueDraft,
    MusicDirectorOutput,
    ShotAudioDraft,
    normalize_indian_epic_names,
)
from ..runner import RoleRunResult, run_role


def _build_music_fallback(
    scenes: list[Scene], shots: list[Shot]
) -> MusicDirectorOutput:
    """Build deterministic fallback MusicCues and ShotAudio assignments."""
    return MusicDirectorOutput(
        cues=[
            MusicCueDraft(
                cue_id=f"cue_{sc.id}",
                scene_id=sc.id,
                mood=sc.mood or "dramatic atmospheric",
                instrumentation="expressive orchestral strings, bansuri flute, gentle percussion",
                tempo_bpm=88 if sc.index == 1 else 104,
                motif_tags=["main_theme", sc.time_of_day],
            )
            for sc in scenes
        ],
        shot_audio=[
            ShotAudioDraft(
                shot_id=sh.id,
                music_cue_id=f"cue_{sh.scene_id}",
                sfx=["ambient nature atmosphere", "gentle wind rustling"],
            )
            for sh in shots
        ],
    )


def _persist_music_output(
    ctx: ToolContext,
    out: MusicDirectorOutput,
    fb_music: MusicDirectorOutput,
    shots: list[Shot],
) -> None:
    """Persist MusicCue nodes and attach music_cue_id + SFX to each Shot."""
    for cue in out.cues or fb_music.cues:
        wt.put_music_cue(
            ctx,
            cue_id=cue.cue_id,
            scene_id=cue.scene_id,
            mood=cue.mood,
            instrumentation=cue.instrumentation,
            tempo_bpm=cue.tempo_bpm,
            motif_tags=cue.motif_tags,
        )
    cue_by_scene = {c.scene_id: c.id for c in ctx.repo.list_music_cues()}
    audio_by_shot = {sa.shot_id: sa for sa in out.shot_audio}
    for sh in shots:
        sa = audio_by_shot.get(sh.id)
        wt.set_shot_audio(
            ctx,
            shot_id=sh.id,
            music_cue_id=(sa.music_cue_id if sa and sa.music_cue_id else None)
            or cue_by_scene.get(sh.scene_id),
            sfx=sa.sfx if sa and sa.sfx else ["ambient scene atmosphere"],
        )


def run_music_director(
    ctx: ToolContext,
    mock_llm: MockLLMClient | None = None,
) -> RoleRunResult:
    """Run MUSIC_DIRECTOR (`music_director_agent`) to score scenes and assign per-shot SFX."""
    scenes = ctx.repo.list_scenes()
    shots = ctx.repo.list_shots()
    story_context = normalize_indian_epic_names(ctx.repo.get_source_text() or "")
    fb_music = _build_music_fallback(scenes, shots)
    scene_list = [{"id": s.id, "heading": s.heading, "mood": s.mood} for s in scenes]
    shot_list = [{"id": sh.id, "scene_id": sh.scene_id} for sh in shots]

    res = run_role(
        role=Role.MUSIC_DIRECTOR,
        ctx=ctx,
        user_prompt=(
            f"Story Context:\n{story_context}\n\n"
            f"Scenes: {scene_list}\n"
            f"Shots: {shot_list}\n"
            "Design scene MusicCues and per-shot SFX matching the cultural, emotional, and visual world of this story."
        ),
        output_schema=MusicDirectorOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: fb_music,
    )
    _persist_music_output(ctx, res.output, fb_music, shots)
    return res
