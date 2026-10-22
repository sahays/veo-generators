"""Gemini audio judgement: are a character's excerpts from different clips one voice?"""

from __future__ import annotations

import os

from ...errors import StoryGraphError
from .contracts import MixJudgement, VoiceJudgement

JUDGE_MODEL = "gemini-3.8-flash"


def _prompt(name: str, n: int) -> str:
    return (
        f"You hear {n} short audio excerpts, each cut from a different animated clip, all "
        f"meant to be the character '{name}'. Ignore words, music and sound effects; judge "
        "only the speaking VOICE (timbre, pitch, apparent age/gender, synthetic quality). "
        "same_speaker_score: 1.0 if every excerpt is clearly the same voice, 0.0 if all differ. "
        "distinct_voices: how many different voices you hear across the excerpts."
    )


def judge_same_voice(
    name: str, excerpts: list[bytes], project: str | None = None
) -> VoiceJudgement:
    """Structured same-voice judgement over WAV excerpts (temperature 0)."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        vertexai=True,
        project=project or os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GEMINI_REGION", "global"),
    )
    parts: list[types.Part | str] = []
    for i, wav in enumerate(excerpts, start=1):
        parts += [
            f"Excerpt {i}:",
            types.Part.from_bytes(data=wav, mime_type="audio/wav"),
        ]
    parts.append(_prompt(name, len(excerpts)))
    try:
        resp = client.models.generate_content(
            model=JUDGE_MODEL,
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VoiceJudgement,
                temperature=0.0,
            ),
        )
    except Exception as exc:
        raise StoryGraphError(f"voice judge failed: {exc}") from exc
    if not resp.text:
        raise StoryGraphError("voice judge EMPTY response")
    return VoiceJudgement.model_validate_json(resp.text)


def judge_mix(clip: bytes, project: str | None = None) -> MixJudgement:
    """Listening-style judgement of one voiced clip: residual Omni voice, SFX, naturalness."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        vertexai=True,
        project=project or os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GEMINI_REGION", "global"),
    )
    prompt = (
        "Listen to this short animated clip's audio. Dialogue was re-voiced and mixed over "
        "the original sound bed. Report: residual_voice = a second, quieter voice audible "
        "under/around the main dialogue ('none', 'faint', 'clear'); sfx_present = whether "
        "non-speech sound effects/ambience are audible; mix_naturalness 0..1 (does the "
        "dialogue sit naturally in the scene, no pumping/gaps); notes = one sentence."
    )
    try:
        resp = client.models.generate_content(
            model=JUDGE_MODEL,
            contents=[types.Part.from_bytes(data=clip, mime_type="video/mp4"), prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MixJudgement,
                temperature=0.0,
            ),
        )
    except Exception as exc:
        raise StoryGraphError(f"mix judge failed: {exc}") from exc
    if not resp.text:
        raise StoryGraphError("mix judge EMPTY response")
    return MixJudgement.model_validate_json(resp.text)
