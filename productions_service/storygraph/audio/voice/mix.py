"""Mix fixed-voice TTS lines over the speech-free bed (one ffmpeg filter graph).

Input 0 is the bed; inputs 1..n are silence-trimmed TTS lines. Each line is
loudness-normalised to `voice_lufs` (consistent voice level across clips), tempo-fitted
with `atempo`, delayed to its placed start, then summed with the bed (`normalize=0` keeps
the bed level) and peak-limited.
"""

from __future__ import annotations

from pathlib import Path

from .media import SAMPLE_RATE
from .timefit import FitPlan

LIMIT = 0.95


def line_chain(index: int, plan: FitPlan, voice_lufs: float) -> str:
    delay_ms = max(0, round(plan.start * 1000))
    return (
        f"[{index}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,"
        f"loudnorm=I={voice_lufs}:TP=-1.5:LRA=11,aresample={SAMPLE_RATE},"
        f"atempo={plan.tempo},adelay={delay_ms}:all=1[v{index}]"
    )


def build_mix_graph(plans: list[FitPlan], voice_lufs: float) -> str:
    """filter_complex string producing `[mix]` from bed + len(plans) line inputs."""
    bed = f"[0:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo[bed]"
    chains = [line_chain(i, p, voice_lufs) for i, p in enumerate(plans, start=1)]
    labels = "[bed]" + "".join(f"[v{i}]" for i in range(1, len(plans) + 1))
    mix = (
        f"{labels}amix=inputs={len(plans) + 1}:duration=first:normalize=0,"
        f"alimiter=limit={LIMIT}[mix]"
    )
    return ";".join([bed, *chains, mix])


def mix_args(
    bed: Path, lines: list[Path], plans: list[FitPlan], voice_lufs: float, out: Path
) -> list[str]:
    inputs = [arg for p in [bed, *lines] for arg in ("-i", str(p))]
    graph = build_mix_graph(plans, voice_lufs)
    return [
        *inputs,
        "-filter_complex",
        graph,
        "-map",
        "[mix]",
        "-ar",
        str(SAMPLE_RATE),
        str(out),
    ]
