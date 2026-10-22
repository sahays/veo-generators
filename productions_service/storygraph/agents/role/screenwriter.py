"""SCREENWRITER role agent runner (`screenwriter_agent`)."""

from __future__ import annotations

from collections.abc import Sequence

from ...adapters.mock import MockLLMClient
from ...clips.builder import build_clips, finalize_clips
from ...clips.limits import clip_rules_text, feedback_block
from ...clips.refs import entity_names, step_refs
from ...clips.species import ActorKind, ActorTraits, actor_traits
from ...clips.text import DialogueRef
from ...physics import enrich_scene_steps
from ...presets import resolve_production_presets
from ...schema import Entity, EntityType, InteractionStep, Role
from ...story import log_scene_duplicates, screenwriter_guard_block
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

_MAX_LINE_WORDS: int = 16


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
    names: dict[str, str],
    traits: dict[str, ActorTraits],
    lang_code: str,
) -> ScreenwriterOutput:
    """Construct a deterministic fallback `ScreenwriterOutput` (steps, dialogue, clips) for `scene_id`."""
    valid_char_ids = set(names)
    speaker_id = next(
        (cid for cid in names if traits.get(cid) is None or traits[cid].can_speak),
        lead_id,
    )
    lead_name = names.get(lead_id, "Arjun")
    speaker_name = names.get(speaker_id, lead_name)
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
    steps = _build_fallback_interaction_steps(sview, lead_id, valid_char_ids)
    line = DialogueLineDraft(
        line_id=f"dlg_{scene_id}_01",
        order_in_scene=1,
        speaker_id=speaker_id,
        text=line_text,
        delivery="low, measured intensity",
        language=lang_code,
    )
    ref = DialogueRef(line_id=line.line_id, speaker_name=speaker_name, text=line_text)
    return ScreenwriterOutput(
        summary=summary_text,
        mood=sview.scene.mood or "tense, cinematic",
        interaction_steps=steps,
        dialogue_lines=[line],
        clips=build_clips(step_refs(steps, names), [ref]),
    )


def _normalize_steps(
    ctx: ToolContext,
    sview: SceneView,
    out: ScreenwriterOutput,
    lead_id: str,
    valid_char_ids: set[str],
) -> list[InteractionStep]:
    """Renumber, sanitize, and Hoare-chain the screenwriter's interaction steps."""
    raw_steps = out.interaction_steps or _build_fallback_interaction_steps(
        sview, lead_id, valid_char_ids
    )
    loc_name = (
        sview.location.canonical_name if sview.location else sview.scene.location_id
    )
    ent_map = {e.id: e for e in ctx.repo.list_entities()}
    return enrich_scene_steps(
        [
            InteractionStep(
                step_index=s_idx,
                actor_id=st.actor_id if st.actor_id in valid_char_ids else lead_id,
                interaction_type=st.interaction_type,
                target_id=st.target_id or sview.scene.location_id,
                action=" ".join(
                    normalize_indian_epic_names(st.action.split(";")[0]).split()[:48]
                ),
                pre_state=normalize_indian_epic_names(st.pre_state),
                contact_mechanics=normalize_indian_epic_names(st.contact_mechanics),
                post_state=normalize_indian_epic_names(st.post_state),
                supported_by=normalize_indian_epic_names(st.supported_by),
                spatial_note=st.spatial_note,
                emotional_beat=st.emotional_beat or out.mood,
                duration_hint_s=max(2.0, min(6.0, float(st.duration_hint_s or 3.5))),
            )
            for s_idx, st in enumerate(raw_steps, start=1)
        ],
        ent_map,
        loc_name,
    )


def _persist_dialogue(
    ctx: ToolContext,
    scene_id: str,
    lines: list[DialogueLineDraft],
    lead_id: str,
    names: dict[str, str],
    lang_code: str,
) -> tuple[list[DialogueRef], dict[str, str]]:
    """Persist dialogue lines; return persisted refs and the LLM line_id -> persisted id map."""
    refs: list[DialogueRef] = []
    id_map: dict[str, str] = {}
    for idx, dl in enumerate(lines, start=1):
        sp_id = dl.speaker_id if dl.speaker_id in names else lead_id
        words = normalize_indian_epic_names(dl.text).split()
        text = " ".join(words[:_MAX_LINE_WORDS])
        eff_lang = (
            lang_code
            if lang_code and not lang_code.lower().startswith("en")
            else (dl.language or lang_code or "en")
        )
        line_id = f"dlg_{scene_id}_{idx:02d}"
        wt.put_dialogue(
            ctx,
            line_id=line_id,
            scene_id=scene_id,
            order_in_scene=idx,
            speaker_id=sp_id,
            addressee_id=dl.addressee_id if dl.addressee_id in names else None,
            text=text,
            delivery=dl.delivery or "natural",
            language=eff_lang,
        )
        id_map[dl.line_id] = line_id
        refs.append(
            DialogueRef(
                line_id=line_id, speaker_name=names.get(sp_id, sp_id), text=text
            )
        )
    return refs, id_map


def _persist_screenwriter_output(
    ctx: ToolContext,
    scene_id: str,
    sview: SceneView,
    out: ScreenwriterOutput,
    lead_id: str,
    names: dict[str, str],
    lang_code: str,
) -> None:
    """Persist steps, dialogue, and the finalized Omni clip partition for `scene_id`."""
    valid_char_ids = set(names)
    norm_steps = _normalize_steps(ctx, sview, out, lead_id, valid_char_ids)
    refs, id_map = _persist_dialogue(
        ctx, scene_id, out.dialogue_lines, lead_id, names, lang_code
    )
    all_names = entity_names(ctx.repo.list_entities())
    clips = finalize_clips(
        scene_id, out.clips, step_refs(norm_steps, all_names), refs, id_map
    )
    wt.update_scene_script(
        ctx,
        scene_id=scene_id,
        summary=normalize_indian_epic_names(out.summary),
        mood=out.mood,
        interaction_steps=norm_steps,
        clips=clips,
    )


def _build_screenwriter_prompt(
    ctx: ToolContext,
    scene_id: str,
    story_context: str,
    sview: SceneView,
    chars: list[Entity],
    lang_code: str,
    traits: dict[str, ActorTraits],
    feedback: Sequence[str] = (),
) -> str:
    """Build the user prompt for `SCREENWRITER` scene steps, dialogue & Omni clip arrangement."""
    meta = ctx.repo.get_project_meta()
    bundle = resolve_production_presets(
        visual_style_id=meta.visual_style_preset if meta else None,
        color_palette_id=meta.color_palette_preset if meta else None,
        director_style_id=meta.director_style_preset if meta else None,
        screenplay_style_id=meta.screenplay_style_preset if meta else None,
        music_style_id=meta.music_style_preset if meta else None,
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
    speaker_list = [
        {"id": c.id, "name": c.canonical_name, "kind": _kind_label(traits.get(c.id))}
        for c in chars
    ]
    return (
        f"Screenplay Style Preset ({bundle.screenplay_style.label}): {bundle.screenplay_style.instruction_prompt}\n\n"
        f"Full Story Context:\n{story_context}\n\n"
        f"Canonical S1 Events in this scene (STRICTLY FOLLOW AND DRAMATIZE THESE EXACT EVENTS):\n{ev_summary}\n\n"
        f"Valid character speaker_ids in this scene: {speaker_list}\n"
        f"TARGET SPOKEN DIALOGUE LANGUAGE: `{lang_code}` — {lang_desc}.\n"
        "CRITICAL RULES (YOU ARRANGE THE SCENE INTO 8–10s GEMINI OMNI CLIPS):\n"
        "1. Author `interaction_steps` as cohesive physical actions (one atomic action each, 2–6 per scene). Do NOT split sub-second micro-gestures into separate steps.\n"
        f"2. {clip_rules_text()}\n"
        "3. Each clip's `omni_prompt` is ONE present-tense paragraph of one continuous moment sent verbatim to the video model: plain sequential language ('First…, then…, finally…') — NEVER seconds, timestamps, or time ranges. Include each of its dialogue lines verbatim with the speaker's name (e.g. `Mira says: \"…\"`). No camera/lighting/colour words (the Director owns them).\n"
        "4. `closing_state` of clip N must equal `opening_state` of clip N+1; reference dialogue by `line_id` in `dialogue_line_ids` (each line in exactly one clip, spoken order).\n"
        "5. Object permanence: every prop and character in the scene is present from the first frame (or enters continuously through a visible doorway); each object exists exactly once; room fixtures stay where they are; a released object stops and rests exactly where it is put. State each prop's start and end place in `pre_state` / `post_state`.\n"
        "6. Species fit: every action and vocalization must match its actor's `kind` above. Only animals bark, meow, neigh, etc.; a non-verbal actor communicates through sounds and body language and gets NO `dialogue_lines`; a character with no mouth speaks voice-only. Write the actor's own name as the subject of each action.\n"
        "7. Keep each step about the props it actually touches; do not restate unrelated props.\n"
        f"8. Write ALL spoken `dialogue_lines[].text` in {lang_desc} (max 14 words per line) and set `dialogue_lines[].language` to `'{lang_code}'`.\n"
        "9. Speech window: every line is spoken DURING the clip's action, never after its last step. In `omni_prompt` place each line right after the step it reacts to and end the clip with a short physical beat after the final line; a wordy clip gets fewer steps.\n"
        "10. Each scene must advance the story: never repeat a gag, action, or line from another scene. An intentional callback must set the line's `delivery` to include 'callback'.\n\n"
        f"{screenwriter_guard_block(ctx.repo, scene_id)}"
        f"{feedback_block(feedback, 'SPEC LINTER REJECTED THE PREVIOUS DRAFT')}"
        f"SCENE VIEW ({scene_id}):\n{sview.model_dump_json(exclude={'shots'})}"
    )


def _kind_label(tr: ActorTraits | None) -> str:
    """Human-readable actor kind for the screenwriter prompt."""
    if tr is None:
        return "person"
    if tr.kind == ActorKind.HYBRID:
        return f"{tr.species or 'hybrid being'} (anthropomorphic: speaks like a person)"
    if tr.kind == ActorKind.ANIMAL:
        sp = tr.species or "animal"
        return (
            f"{sp} (speaks)"
            if tr.can_speak
            else f"{sp} (non-verbal: {tr.vocalization})"
        )
    voice = "" if tr.has_mouth else " (no mouth: voice only)"
    return f"{tr.kind.value}{voice}"


def run_screenwriter_for_scene(
    ctx: ToolContext,
    scene_id: str,
    language: str = "en",
    mock_llm: MockLLMClient | None = None,
    feedback: Sequence[str] = (),
) -> RoleRunResult:
    """Run SCREENWRITER (`screenwriter_agent`) to author steps, dialogue, and Omni clips for a scene."""
    sview = scene_view(ctx.repo, scene_id)
    chars = [
        e for e in sview.entities_in_scene if e.entity_type == EntityType.CHARACTER
    ] or ctx.repo.list_entities(entity_type=EntityType.CHARACTER)
    lead_id = chars[0].id if chars else "char_arjun"
    names = entity_names(chars) or {lead_id: "Arjun"}
    story_context = normalize_indian_epic_names(ctx.repo.get_source_text() or "")
    lang_code = (language or "en").strip()
    traits = actor_traits(chars, ctx.repo.list_appearances())

    res = run_role(
        role=Role.SCREENWRITER,
        ctx=ctx,
        user_prompt=_build_screenwriter_prompt(
            ctx, scene_id, story_context, sview, chars, lang_code, traits, feedback
        ),
        output_schema=ScreenwriterOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: _build_screenwriter_fallback(
            scene_id, sview, lead_id, names, traits, lang_code
        ),
    )
    _persist_screenwriter_output(
        ctx, scene_id, sview, res.output, lead_id, names, lang_code
    )
    log_scene_duplicates(ctx.repo, scene_id, who=str(Role.SCREENWRITER))
    return res
