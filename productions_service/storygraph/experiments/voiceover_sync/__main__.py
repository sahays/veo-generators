"""CLI: python -m storygraph.experiments.voiceover_sync --export DIR --clips DIR --out DIR."""

from __future__ import annotations

import argparse
import logging
import tempfile
from pathlib import Path

from ...adapters.gemini_tts import GeminiTTSSynthesizer
from ...adapters.transcribe import GeminiTranscriber
from ...audio.voice.logs import log_ctx
from ...audio.voice.media import MediaTools
from ...audio.voice.separation import make_remover
from ...audio.voice.sync import SyncDeps
from ...config import AudioCfg
from ...errors import StoryGraphError
from ...schemas.voice import SpeechRemoval, VoiceProfile
from .cases import cast_voices, load_cases, load_cast
from .contracts import ClipCase, ClipEval, ExperimentReport
from .judge import judge_same_voice
from .metrics import cut_excerpt
from .retry import RetryingSynthesizer, RetryingTranscriber, with_backoff
from .runner import run_case


def _deps(removers: list[SpeechRemoval], project: str) -> dict[SpeechRemoval, SyncDeps]:
    media = MediaTools()
    # No pro fallback: flash is ~17 s per clip, the fallback took minutes per call.
    transcriber = RetryingTranscriber(
        GeminiTranscriber(project=project, fallback_model=None)
    )
    tts = RetryingSynthesizer(GeminiTTSSynthesizer(project=project))
    return {
        r: SyncDeps(transcriber, tts, make_remover(r, AudioCfg().duck_db, media), media)
        for r in removers
    }


def _excerpts(
    cases: list[ClipCase], evals: list[ClipEval], who: str, voiced: bool, tmp: Path
) -> list[bytes]:
    """One excerpt per clip line of `who` (voiced placement or original Omni slot)."""
    src = {c.clip_id: c.path for c in cases}
    out: list[bytes] = []
    for ev in evals:
        for i, p in enumerate(ev.placements):
            if p.speaker_id != who or p.estimated_slot:
                continue
            path = Path(ev.voiced_path) if voiced else src[ev.clip_id]
            win = (
                (p.placed_start_s, p.placed_end_s)
                if voiced
                else (p.slot_start_s, p.slot_end_s)
            )
            out.append(cut_excerpt(path, win, tmp / f"{ev.clip_id}_{i}_{voiced}.wav"))
    return out


def _consistency(
    report: ExperimentReport, cases: list[ClipCase], first: str, project: str
) -> None:
    evals = [e for e in report.clips if e.remover == first]
    with tempfile.TemporaryDirectory() as tmp:
        for who in report.voices:
            for variant, voiced in (("omni", False), ("voiced", True)):
                clips = _excerpts(cases, evals, who, voiced, Path(tmp))
                if len(clips) >= 2:
                    report.judgements[f"{who}|{variant}"] = with_backoff(
                        lambda w=who, c=clips: judge_same_voice(w, c, project), "judge"
                    )
                f0s = [
                    f
                    for e in evals
                    for ln in e.lines
                    if ln.speaker_id == who
                    if (f := ln.voiced_f0_hz if voiced else ln.orig_f0_hz) is not None
                ]
                if len(f0s) >= 2:
                    report.f0_spread_hz[f"{who}|{variant}"] = round(
                        max(f0s) - min(f0s), 1
                    )


def _safe_case(
    case: ClipCase,
    voices: dict[str, VoiceProfile],
    deps: dict[SpeechRemoval, SyncDeps],
    out: Path,
) -> list[ClipEval]:
    """One case; a persistent API failure skips the clip instead of losing the run."""
    try:
        return run_case(case, voices, deps, out)
    except StoryGraphError as exc:
        logging.getLogger(__name__).warning(
            "Experiment clip skipped",
            extra=log_ctx(
                "experiments.voiceover_sync.main",
                "experiment_clip_skipped",
                str(exc)[:200],
                "run_case raised after backoff",
                clip_id=case.clip_id,
            ),
        )
        return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", type=Path, required=True)
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--removers", default="duck,demucs")
    ap.add_argument("--project", default="aug18-25-3")
    ap.add_argument(
        "--judge-only", action="store_true", help="reuse out/report.json clips"
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    cast, source = load_cast(args.export)
    cases = load_cases(args.export, args.clips, cast)
    voices = cast_voices(cast, source, cases)
    removers: list[SpeechRemoval] = [
        r for r in ("duck", "demucs") if r in args.removers.split(",")
    ]
    deps = _deps(removers, args.project)
    report = ExperimentReport(
        voices={k: f"{v.voice_name} ({v.archetype})" for k, v in voices.items()}
    )
    out = args.out / "report.json"
    if args.judge_only:
        report = ExperimentReport.model_validate_json(out.read_text("utf-8"))
    todo = [] if args.judge_only else cases  # judge-only reuses the saved clips
    for case in todo:
        report.clips += _safe_case(case, voices, deps, args.out)
        out.write_text(report.model_dump_json(indent=2), "utf-8")  # partial-safe
    _consistency(report, cases, removers[0], args.project)
    out.write_text(report.model_dump_json(indent=2), "utf-8")
    logging.getLogger(__name__).info(
        "Voiceover experiment report written",
        extra=log_ctx(
            "experiments.voiceover_sync.main",
            "experiment_report_written",
            "voiceover_sync_v1 evaluation",
            "ExperimentReport JSON",
            report_path=str(args.out / "report.json"),
        ),
    )


if __name__ == "__main__":
    main()
