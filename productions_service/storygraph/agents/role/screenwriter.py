"""SCREENWRITER role agent runner (`screenwriter_agent`)."""

from __future__ import annotations

from ...adapters.mock import MockLLMClient
from ...schema import Entity, EntityType, Role
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


def _build_screenwriter_fallback(
    scene_id: str,
    sview: SceneView,
    lead_id: str,
    lead_name: str,
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
    out: ScreenwriterOutput,
    lead_id: str,
    valid_char_ids: set[str],
    lang_code: str,
) -> None:
    """Persist scene script summary, mood, and dialogue lines produced by `SCREENWRITER`."""
    wt.update_scene_script(
        ctx,
        scene_id=scene_id,
        summary=normalize_indian_epic_names(out.summary),
        mood=out.mood,
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
    scene_id: str,
    story_context: str,
    sview: SceneView,
    chars: list[Entity],
    lang_code: str,
) -> str:
    """Build the user prompt for `SCREENWRITER` scene dialogue generation."""
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
        f"Full Story Context:\n{story_context}\n\n"
        f"Canonical S1 Events in this scene (STRICTLY FOLLOW AND DRAMATIZE THESE EXACT EVENTS):\n{ev_summary}\n\n"
        f"Valid character speaker_ids in this scene: {speaker_list}\n"
        f"TARGET SPOKEN DIALOGUE LANGUAGE: `{lang_code}` — {lang_desc}.\n"
        "CRITICAL RULES:\n"
        "1. Your `summary` and `dialogue_lines` MUST strictly dramatize the S1 `events` listed above for this scene.\n"
        f"2. Write ALL spoken `dialogue_lines[].text` in {lang_desc} (max 10 words per line) and set `dialogue_lines[].language` to `'{lang_code}'`.\n\n"
        f"SCENE VIEW ({scene_id}):\n{sview.model_dump_json()}"
    )


def run_screenwriter_for_scene(
    ctx: ToolContext,
    scene_id: str,
    language: str = "en",
    mock_llm: MockLLMClient | None = None,
) -> RoleRunResult:
    """Run SCREENWRITER (`screenwriter_agent`) to author scene script summary, mood, and dialogue lines."""
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
            scene_id, story_context, sview, chars, lang_code
        ),
        output_schema=ScreenwriterOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: _build_screenwriter_fallback(
            scene_id, sview, lead_id, lead_name, lang_code
        ),
    )
    _persist_screenwriter_output(
        ctx, scene_id, res.output, lead_id, valid_char_ids, lang_code
    )
    return res
