"""Stem routing: guide timings -> dialogue stem on silence; SFX keyed to speech; S10 render."""

from __future__ import annotations

from pathlib import Path

import pytest
from storygraph.adapters.transcribe import Transcript, TranscriptSegment
from storygraph.assembly.readiness import ReadyShot
from storygraph.assembly.stem_clips import render_stem_clips
from storygraph.audio.stems import RenderTools, StemDeps, build_stems
from storygraph.audio.voice.media import MediaTools
from storygraph.audio.voice.separation import DuckRemover
from storygraph.audio.voice.sync import SyncDeps
from storygraph.audio.voice.timing import SpeechLine, Window
from storygraph.config import AssemblyCfg, AudioCfg
from storygraph.repo import Repo
from storygraph.schema import GenerationRun, Role, StemSet, Status, VoiceProfile


class _Media:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args: list[str]) -> None:
        self.commands.append(args)
        Path(args[-1]).write_bytes(b"OUT:" + Path(args[-1]).name.encode())

    def probe(self, path: Path) -> float:
        return 1.5 if path.name.startswith("line_") else 8.0


class _Transcriber:
    def transcribe(
        self, clip: bytes, speakers: list[str], langs: list[str]
    ) -> Transcript:
        seg = TranscriptSegment(
            t_start=1.0, t_end=3.0, text="Hold fast.", speaker="Pip"
        )
        return Transcript(segments=[seg])


class _TTS:
    def synthesize(
        self, text: str, voice: VoiceProfile, lang: str, target_s: float | None
    ) -> bytes:
        return b"RIFF"


class _Sfx:
    name = "demucs"

    def __init__(self) -> None:
        self.speech: list[Window] = []

    def make(self, guide_audio: Path, speech: list[Window], work: Path) -> Path:
        self.speech = speech
        out = work / "sfx_stem.wav"
        out.write_bytes(b"SFX")
        return out


def test_build_stems_routes_tts_onto_silence_and_keys_sfx_on_guide_speech() -> None:
    media, sfx = _Media(), _Sfx()
    tools = MediaTools(run=media.run, probe=media.probe)
    sync = SyncDeps(
        _Transcriber(),
        _TTS(),
        DuckRemover(media=tools),
        tools,
        vad=lambda _: [(6.0, 7.0)],
    )
    line = SpeechLine("l1", "char_pip", "Pip", "en", "Hold fast.")
    built = build_stems(b"mp4", [line], {"char_pip": VoiceProfile(voice_name="Zephyr")},
                        AudioCfg(mode="stems"), StemDeps(sync, sfx))  # fmt: skip
    mix = next(c for c in media.commands if "-filter_complex" in c)
    assert mix[1].endswith("silence.wav")  # dialogue stem has no Omni bed under it
    assert sfx.speech == [
        pytest.approx((0.85, 3.15))
    ]  # transcript speech, not mix-VAD SFX
    assert built.dialogue == b"OUT:dialogue.flac" and built.sfx == b"OUT:sfx.flac"
    assert built.lines[0].placed_start_s == 1.0


def _run(repo: Repo, shot: str, stems: StemSet | None) -> GenerationRun:
    run = GenerationRun(
        id=f"run_{shot}", created_by=Role.PIPELINE, status=Status.APPROVED, shot_id=shot,
        attempt=1, provider="gemini", model="omni", compiled_prompt="p", seed=1,
        package_hash="h", output_video_uri=f"{shot}.mp4", stems=stems,
    )  # fmt: skip
    return repo.add_generation_run(run)


def test_s10_renders_shots_with_stems_and_keeps_omni_clip_otherwise(
    tmp_repo: Repo,
) -> None:
    put = tmp_repo.blobs.put_bytes
    stems = StemSet(
        dialogue_uri=put("d.flac", b"DIA", "audio/flac"),
        sfx_uri=put("s.flac", b"SFX", "audio/flac"),
        duration_s=8.0,
    )
    _run(tmp_repo, "shot_a", stems)
    _run(tmp_repo, "shot_b", None)
    media = _Media()
    tools = RenderTools(
        MediaTools(run=media.run, probe=media.probe), measure=lambda _: -20.0
    )
    ready = [
        ReadyShot(shot_id=s, run_id=f"run_{s}", video_uri=f"{s}.mp4")
        for s in ("shot_a", "shot_b")
    ]
    out = render_stem_clips(
        tmp_repo, ready, [b"PIC_A", b"PIC_B"], (AudioCfg(), AssemblyCfg()), tools
    )
    assert out.clips == [b"OUT:mixed.mp4", b"PIC_B"]
    assert out.duck_key is None  # a shot without stems disables the dialogue-only key
    render = next(c for c in media.commands if "-filter_complex" in c)
    assert (
        render[render.index("-map") + 1] == "0:v:0"
    )  # Omni picture, guide audio dropped
    assert (
        "volume=4.0dB" in render[render.index("-filter_complex") + 1]
    )  # -20 -> -16 LUFS
