"""Mix pipeline with fake transcriber/TTS/ffmpeg: fixed voices, placement, graph and mux."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from storygraph.adapters.transcribe import Transcript, TranscriptSegment
from storygraph.audio.voice.media import MediaTools
from storygraph.audio.voice.separation import DuckRemover
from storygraph.audio.voice.sync import SyncDeps, voice_clip
from storygraph.audio.voice.timing import SpeechLine, Window
from storygraph.config import AudioCfg
from storygraph.schema import VoiceProfile

CLIP_S = 8.0
TTS_S = {"line_0.wav": 2.0, "line_1.wav": 3.0}


class _Transcriber:
    def transcribe(
        self, clip_bytes: bytes, speakers: list[str], lang_hints: list[str]
    ) -> Transcript:
        return Transcript(
            segments=[
                TranscriptSegment(
                    t_start=0.5, t_end=2.5, text="The seal shall break.", speaker="Pip"
                ),
                TranscriptSegment(
                    t_start=3.5,
                    t_end=5.5,
                    text="Then give it back to me.",
                    speaker="Ava",
                ),
                TranscriptSegment(t_start=6.5, t_end=7.0, text="Wow!", speaker="Ava"),
            ]
        )


class _TTS:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, float | None]] = []

    def synthesize(
        self, text: str, voice: VoiceProfile, lang: str, target_s: float | None
    ) -> bytes:
        self.calls.append((text, voice.voice_name, lang, target_s))
        return b"RIFFfake"


class _Media:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args: list[str]) -> None:
        self.commands.append(args)
        Path(args[-1]).write_bytes(b"OUT:" + Path(args[-1]).name.encode())

    def probe(self, path: Path) -> float:
        return TTS_S.get(path.name, CLIP_S)


class _RecordingRemover(DuckRemover):
    seen: ClassVar[list[list[Window]]] = []

    def remove(self, audio_wav: Path, windows: list[Window], work: Path) -> Path:
        _RecordingRemover.seen.append(windows)
        return super().remove(audio_wav, windows, work)


def test_voice_clip_uses_fixed_voices_and_places_lines_in_graph() -> None:
    media, tts = _Media(), _TTS()
    tools = MediaTools(run=media.run, probe=media.probe)
    deps = SyncDeps(
        _Transcriber(),
        tts,
        _RecordingRemover(media=tools),
        tools,
        vad=lambda _: [(7.5, 7.8)],
    )
    lines = [
        SpeechLine("l1", "char_pip", "Pip", "en-IN", "The seal shall break."),
        SpeechLine("l2", "char_ava", "Ava", "hi", "Then give it back to me."),
    ]
    voices = {
        "char_pip": VoiceProfile(voice_name="Puck"),
        "char_ava": VoiceProfile(voice_name="Kore"),
    }
    out = voice_clip(b"mp4", lines, voices, AudioCfg(voiceover="sync"), deps)

    assert tts.calls == [
        ("The seal shall break.", "Puck", "en-IN", pytest.approx(1.7)),  # 0.85 x window
        ("Then give it back to me.", "Kore", "hi", pytest.approx(1.7)),
    ]
    assert [(v.placed_start_s, v.tempo) for v in out.lines] == [(0.5, 1.0), (3.5, 1.35)]
    # Unscripted "Wow!" and VAD-only activity (missed by the transcript) are both ducked.
    assert _RecordingRemover.seen[-1][-2:] == [
        pytest.approx((6.35, 7.15)),
        pytest.approx((7.35, 7.95)),
    ]
    mix = next(c for c in media.commands if "-filter_complex" in c)
    graph = mix[mix.index("-filter_complex") + 1]
    assert (
        "atempo=1.35,adelay=3500:all=1[v2]" in graph and "adelay=500:all=1[v1]" in graph
    )
    assert "amix=inputs=3:duration=first:normalize=0" in graph
    mux = media.commands[-1]
    assert mux[mux.index("-c:v") + 1] == "copy" and mux[mux.index("-t") + 1] == "8.000"
    assert out.video == b"OUT:voiced.mp4"
