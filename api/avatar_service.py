"""Avatar service — text answer generation and per-turn orchestration."""

import logging
from typing import Optional

from google.genai import types

import deps
from ai_helpers import compute_usage, resolve_model
from models import Avatar, AvatarStyle, AvatarTurn, UsageMetrics

logger = logging.getLogger(__name__)


STYLE_INSTRUCTIONS = {
    AvatarStyle.talkative: "talkative — friendly, warm, expressive but still concise",
    AvatarStyle.funny: "funny — light, playful, drop in a bit of humor",
    AvatarStyle.serious: "serious — measured, factual, no jokes",
    AvatarStyle.cynical: "cynical — wry, slightly skeptical, dry tone",
    AvatarStyle.to_the_point: "to-the-point — minimal words, direct, no preamble",
}


def build_system_instruction(avatar: Avatar) -> str:
    """System prompt that shapes Gemini's reply for an avatar turn."""
    style_note = STYLE_INSTRUCTIONS.get(
        avatar.style, STYLE_INSTRUCTIONS[AvatarStyle.to_the_point]
    )
    persona_block = (
        f"\nPersona note: {avatar.persona_prompt.strip()}"
        if avatar.persona_prompt
        else ""
    )
    return (
        f"You are {avatar.name}, an AI avatar that replies as a short lip-synced video.{persona_block}\n"
        f"Tone: {style_note}.\n"
        "Reply rules:\n"
        "- Your reply will be turned into an ≤ 8-second video. Stay under 25 words.\n"
        "- One short paragraph. No lists, no markdown, no preamble like 'Sure!' or 'Of course'.\n"
        "- Be specific and answer the question; do not filler-pad."
    )


def _format_history(history: list[dict]) -> list[types.Content]:
    """Map a list of {role, content} dicts to genai Content for history context."""
    contents: list[types.Content] = []
    for msg in history[-10:]:  # cap context
        role = msg.get("role", "user")
        text = msg.get("content", "")
        if not text:
            continue
        contents.append(
            types.Content(
                role="user" if role == "user" else "model",
                parts=[types.Part.from_text(text=text)],
            )
        )
    return contents


def _resolve_text_model(model_id: Optional[str]) -> str:
    return resolve_model(
        deps.firestore_svc,
        "text",
        "GEMINI_AGENT_ORCHESTRATOR",
        "gemini-3.1-flash-lite-preview",
        model_id,
    )


def answer_question(
    avatar: Avatar,
    question: str,
    history: Optional[list[dict]] = None,
    model_id: Optional[str] = None,
    region: Optional[str] = None,
) -> tuple[str, UsageMetrics, str]:
    """Run Gemini Flash Lite with the avatar's persona to generate a short reply.

    Returns (answer_text, usage, resolved_model_id).
    """
    if not deps.gemini_svc:
        raise RuntimeError("Gemini service unavailable")

    resolved_model = _resolve_text_model(model_id)
    client = deps.gemini_svc._get_client(region)

    contents = _format_history(history or [])
    contents.append(
        types.Content(role="user", parts=[types.Part.from_text(text=question)])
    )

    response = client.models.generate_content(
        model=resolved_model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=build_system_instruction(avatar),
            temperature=0.8,
            max_output_tokens=120,
        ),
    )
    answer_text = (response.text or "").strip()
    usage = compute_usage(response, resolved_model)
    return answer_text, usage, resolved_model


def answer_audio_question(
    avatar: Avatar,
    audio_bytes: bytes,
    mime_type: str,
    history: Optional[list[dict]] = None,
    model_id: Optional[str] = None,
    region: Optional[str] = None,
) -> tuple[str, UsageMetrics, str]:
    """Send raw audio (≤ 10 s, browser MediaRecorder output) to Gemini and let
    it both understand the question and reply per the avatar's persona.

    Returns (answer_text, usage, resolved_model_id).
    """
    if not deps.gemini_svc:
        raise RuntimeError("Gemini service unavailable")

    resolved_model = _resolve_text_model(model_id)
    client = deps.gemini_svc._get_client(region)

    contents = _format_history(history or [])
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)],
        )
    )

    response = client.models.generate_content(
        model=resolved_model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=build_system_instruction(avatar),
            temperature=0.8,
            max_output_tokens=120,
        ),
    )
    answer_text = (response.text or "").strip()
    usage = compute_usage(response, resolved_model)
    return answer_text, usage, resolved_model


def build_render_prompt(avatar: Avatar, answer_text: str) -> str:
    """Veo prompt: image-to-video of the avatar speaking the answer.

    Preserves the reference image's setting and background — Veo decides the
    framing and backdrop from the input portrait rather than being instructed
    to replace anything. Phrased as a scene description so Veo's safety filter
    doesn't read it as command-style image manipulation.
    """
    style_note = STYLE_INSTRUCTIONS.get(
        avatar.style, STYLE_INSTRUCTIONS[AvatarStyle.to_the_point]
    )
    return (
        "The main person from the reference image speaks directly to camera. "
        "Lips matching the audio, "
        f'saying: "{answer_text}". '
        f"Tone: {style_note}. Natural delivery. "
        "Preserve the look, framing, and setting of the reference image."
    )


def create_pending_turn(
    avatar: Avatar,
    question: str,
    answer_text: str,
    usage: UsageMetrics,
    text_model_id: str,
    invite_code: Optional[str],
    region: Optional[str] = None,
) -> AvatarTurn:
    """Persist an AvatarTurn in `pending` state — worker will render the video."""
    if not deps.firestore_svc:
        raise RuntimeError("Firestore service unavailable")
    turn = AvatarTurn(
        avatar_id=avatar.id,
        question=question,
        answer_text=answer_text,
        status="pending",
        progress_pct=0,
        usage=usage,
        model_id=text_model_id,
        region=region,
        invite_code=invite_code,
    )
    deps.firestore_svc.create_avatar_turn(turn)
    return turn
