"""Gemini TTS prompt safety: only the line may be spoken; read-aloud instructions are caught."""

from __future__ import annotations

from storygraph.adapters.gemini_tts import PCM_RATE, plausible_length, tts_prompt
from storygraph.schema import VoiceProfile


def test_prompt_paces_to_target_with_a_single_directive_colon() -> None:
    voice = VoiceProfile(
        voice_name="Zephyr", style_prompt="bright: crisp, slightly robotic"
    )
    prompt = tts_prompt("Ruko: abhi nahi.", voice, "hi", 2.44)
    directive, spoken = prompt.split(": ", 1)
    assert spoken == "Ruko: abhi nahi."
    assert ":" not in directive and "in Hindi" in directive
    assert "about 2.4 seconds" in directive
    assert "seconds" not in tts_prompt("Hi.", voice, "en", None)  # no window -> no pace


def test_audio_far_longer_than_the_line_is_implausible() -> None:
    line = "The sanctuary is unbroken, Ava. Nothing has slipped away."
    two_point_eight_s = b"\0" * int(2 * PCM_RATE * 2.8)
    twenty_three_s = b"\0" * int(2 * PCM_RATE * 23.0)
    assert plausible_length(two_point_eight_s, line)
    assert not plausible_length(twenty_three_s, line)
