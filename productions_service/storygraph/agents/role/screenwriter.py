"""SCREENWRITER role agent runner (`screenwriter_agent`)."""

from __future__ import annotations

from ...adapters.mock import MockLLMClient
from ...presets import resolve_production_presets
from ...schema import Entity, EntityType, InteractionStep, Role
from ...tools import write_tools as wt
from ...tools.registry import ToolContext
from ...tools.role_helpers import (
    LANGUAGE_PROMPT_NAMES,
    DialogueLineDraft,
    ScreenwriterOutput,
    normalize_indian_epic_names,
)
from ...views import SceneView, scene_view
from ..runner import RoleRunResult, run_role


def _build_fallback_interaction_steps(
    sview: SceneView,
    lead_id: str,
    valid_char_ids: set[str],
) -> list[InteractionStep]:
    """Construct ordered 1-action-at-a-time fallback `InteractionStep` entries for `sview`."""
    steps: list[InteractionStep] = []
    for idx, ev in enumerate(sview.events, start=1):
        actor = next((p for p in ev.participants if p in valid_char_ids), lead_id)
        other = next(
            (p for p in ev.participants if p != actor), sview.scene.location_id
        )
        itype = (
            "character"
            if other in valid_char_ids
            else ("prop" if other.startswith("obj_") else "environment")
        )
        clause = ev.summary.split(";")[0].strip() or f"Acts in {sview.scene.heading}."
        steps.append(
            InteractionStep(
                step_index=idx,
                actor_id=actor,
                interaction_type=itype,  # type: ignore[arg-type]
                target_id=other,
                action=" ".join(normalize_indian_epic_names(clause).split()[:22]),
                spatial_note="center frame",
                emotional_beat=sview.scene.mood or "focused",
            )
        )
    if not steps:
        steps.append(
            InteractionStep(
                step_index=1,
                actor_id=lead_id,
                interaction_type="environment",
                target_id=sview.scene.location_id,
                action=" ".join(
                    (sview.scene.summary or sview.scene.heading)
                    .split(";")[0]
                    .split()[:22]
                ),
                spatial_note="center frame",
                emotional_beat=sview.scene.mood or "cinematic",
            )
        )
    return steps


def _build_screenwriter_fallback(
    scene_id: str,
    sview: SceneView,
    lead_id: str,
    lead_name: str,
    valid_char_ids: set[str],
    lang_code: str,
) -> ScreenwriterOutput:
    """Construct a deterministic fallback `ScreenwriterOutput` for `scene_id`."""
    summary_text = (
        " ".join(ev.summary for ev in sview.events if ev.summary)
        or sview.scene.summary
        or f"{lead_name} acts in {sview.scene.heading}."
    )
    line_text = (
        "हमें धर्म और सत्य के मार्ग पर अडिग रहना होगा।"
        if lang_code.lower().startswith("hi")
        else "Every detail leads back to this moment."
    )
    return ScreenwriterOutput(
        summary=summary_text,
        mood=sview.scene.mood or "tense, cinematic",
        interaction_steps=_build_fallback_interaction_steps(
            sview, lead_id, valid_char_ids
        ),
        dialogue_lines=[
            DialogueLineDraft(
                line_id=f"dlg_{scene_id}_01",
                order_in_scene=1,
                speaker_id=lead_id,
                text=line_text,
                delivery="low, measured intensity",
                language=lang_code,
            )
        ],
    )


def _persist_screenwriter_output(
    ctx: ToolContext,
    scene_id: str,
    sview: SceneView,
    out: ScreenwriterOutput,
    lead_id: str,
    valid_char_ids: set[str],
    lang_code: str,
) -> None:
    """Persist scene script summary, mood, algorithmic interaction_steps, and dialogue lines."""
    raw_steps = out.interaction_steps or _build_fallback_interaction_steps(
        sview, lead_id, valid_char_ids
    )
    norm_steps = [
        InteractionStep(
            step_index=s_idx,
            actor_id=st.actor_id if st.actor_id in valid_char_ids else lead_id,
            interaction_type=st.interaction_type,
            target_id=st.target_id or sview.scene.location_id,
            action=" ".join(
                normalize_indian_epic_names(st.action.split(";")[0]).split()[:24]
            ),
            spatial_note=st.spatial_note,
            emotional_beat=st.emotional_beat or out.mood,
        )
        for s_idx, st in enumerate(raw_steps, start=1)
    ]
    wt.update_scene_script(
        ctx,
        scene_id=scene_id,
        summary=normalize_indian_epic_names(out.summary),
        mood=out.mood,
        interaction_steps=norm_steps,
    )
    for idx, dl in enumerate(out.dialogue_lines, start=1):
        sp_id = dl.speaker_id if dl.speaker_id in valid_char_ids else lead_id
        clean_text = normalize_indian_epic_names(dl.text)
        words = clean_text.split()
        eff_lang = (
            lang_code
            if lang_code and not lang_code.lower().startswith("en")
            else (dl.language or lang_code or "en")
        )
        wt.put_dialogue(
            ctx,
            line_id=f"dlg_{scene_id}_{idx:02d}",
            scene_id=scene_id,
            order_in_scene=idx,
            speaker_id=sp_id,
            addressee_id=dl.addressee_id if dl.addressee_id in valid_char_ids else None,
            text=" ".join(words[:11]) if len(words) > 11 else clean_text,
            delivery=dl.delivery or "natural",
            language=eff_lang,
        )


def _build_screenwriter_prompt(
    ctx: ToolContext,
    scene_id: str,
    story_context: str,
    sview: SceneView,
    chars: list[Entity],
    lang_code: str,
) -> str:
    """Build the user prompt for `SCREENWRITER` scene algorithm & dialogue generation."""
    meta = ctx.repo.get_project_meta()
    bundle = resolve_production_presets(
        visual_style_id=meta.visual_style_preset if meta else None,
        color_palette_id=meta.color_palette_preset if meta else None,
        director_style_id=meta.director_style_preset if meta else None,
    )
    lang_desc = LANGUAGE_PROMPT_NAMES.get(lang_code.lower(), lang_code)
    ev_summary = [
        {
            "event_id": ev.id,
            "story_order": ev.story_order,
            "summary": ev.summary,
            "participants": ev.participants,
        }
        for ev in sview.events
    ]
    speaker_list = [{"id": c.id, "name": c.canonical_name} for c in chars]
    return (
        f"Screenplay Style Preset ({bundle.screenplay_style.label}): {bundle.screenplay_style.instruction_prompt}\n\n"
        f"Full Story Context:\n{story_context}\n\n"
        f"Canonical S1 Events in this scene (STRICTLY FOLLOW AND DRAMATIZE THESE EXACT EVENTS):\n{ev_summary}\n\n"
        f"Valid character speaker_ids in this scene: {speaker_list}\n"
        f"TARGET SPOKEN DIALOGUE LANGUAGE: `{lang_code}` — {lang_desc}.\n"
        "CRITICAL RULES:\n"
        "1. Author `interaction_steps` like an algorithm: ordered 1-action-at-a-time steps (`actor_id`, `interaction_type`, `target_id`, `action`).\n"
        "2. Your `summary`, `interaction_steps`, and `dialogue_lines` MUST strictly dramatize the S1 `events` listed above.\n"
        f"3. Write ALL spoken `dialogue_lines[].text` in {lang_desc} (max 10 words per line) and set `dialogue_lines[].language` to `'{lang_code}'`.\n\n"
        f"SCENE VIEW ({scene_id}):\n{sview.model_dump_json()}"
    )


def run_screenwriter_for_scene(
    ctx: ToolContext,
    scene_id: str,
    language: str = "en",
    mock_llm: MockLLMClient | None = None,
) -> RoleRunResult:
    """Run SCREENWRITER (`screenwriter_agent`) to author scene script summary, mood, interaction_steps, and dialogue."""
    sview = scene_view(ctx.repo, scene_id)
    chars = [
        e for e in sview.entities_in_scene if e.entity_type == EntityType.CHARACTER
    ] or ctx.repo.list_entities(entity_type=EntityType.CHARACTER)
    lead_id = chars[0].id if chars else "char_arjun"
    lead_name = chars[0].canonical_name if chars else "Arjun"
    valid_char_ids = {c.id for c in chars}
    story_context = normalize_indian_epic_names(ctx.repo.get_source_text() or "")
    lang_code = (language or "en").strip()

    res = run_role(
        role=Role.SCREENWRITER,
        ctx=ctx,
        user_prompt=_build_screenwriter_prompt(
            ctx, scene_id, story_context, sview, chars, lang_code
        ),
        output_schema=ScreenwriterOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: _build_screenwriter_fallback(
            scene_id, sview, lead_id, lead_name, valid_char_ids, lang_code
        ),
    )
    _persist_screenwriter_output(
        ctx, scene_id, sview, res.output, lead_id, valid_char_ids, lang_code
    )
    return res
