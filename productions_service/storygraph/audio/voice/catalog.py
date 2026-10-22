"""Gemini TTS prebuilt-voice catalog grouped by character archetype.

Each archetype lists candidate prebuilt voices (documented gender/register) in preference
order, plus a short tone phrase (no colons: Gemini TTS may read instructions aloud) that
steers delivery without changing the fixed voice.
"""

from __future__ import annotations

from typing import Final

from ...schemas.voice import VoiceArchetype

ARCHETYPE_VOICES: Final[dict[VoiceArchetype, tuple[str, ...]]] = {
    "robot": ("Puck", "Fenrir", "Laomedeia", "Sadachbia", "Zephyr"),
    "child_female": ("Leda", "Zephyr", "Autonoe", "Laomedeia"),
    "child_male": ("Puck", "Fenrir", "Sadachbia"),
    "adult_female": ("Kore", "Aoede", "Erinome", "Despina", "Sulafat", "Callirrhoe"),
    "adult_male": ("Orus", "Charon", "Iapetus", "Alnilam", "Achird"),
    "elder_female": ("Gacrux", "Vindemiatrix", "Sulafat"),
    "elder_male": ("Algenib", "Rasalgethi", "Sadaltager"),
    "creature": ("Fenrir", "Puck", "Umbriel"),
    "neutral": ("Achernar", "Schedar", "Umbriel", "Zubenelgenubi"),
}

ARCHETYPE_STYLE: Final[dict[VoiceArchetype, str]] = {
    "robot": "bright, brisk, crisp, slightly robotic",
    "child_female": "bright, clear, lively young girl's",
    "child_male": "bright, energetic young boy's",
    "adult_female": "warm, clear, natural young woman's",
    "adult_male": "steady, clear, natural adult man's",
    "elder_female": "warm, gentle, unhurried elderly woman's",
    "elder_male": "deep, calm, unhurried elderly man's",
    "creature": "playful, animated storybook creature's",
    "neutral": "warm, clear, natural",
}


def candidates(archetype: VoiceArchetype) -> tuple[str, ...]:
    """Candidate prebuilt voice names for `archetype` (never empty)."""
    return ARCHETYPE_VOICES.get(archetype) or ARCHETYPE_VOICES["neutral"]
