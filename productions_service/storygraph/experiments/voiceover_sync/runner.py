"""Voiceover-sync experiment runner: voice each clip per remover, then measure.

Measures per line: intelligibility/completeness (re-transcribe + match_dialogue), onset
offset vs Omni's original segment, median F0; per clip: SFX bed level outside speech and
residual unscripted speech; per character: Gemini same-voice judgement + F0 spread.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ...adapters.transcribe import Transcriber, Transcript
from ...audio.voice.logs import log_ctx
from ...audio.stems import (
    DemucsSfx,
    RenderTools,
    StemAudio,
    StemDeps,
    build_stems,
    render_stem_clip,
)
from ...audio.voice.sync import SyncDeps, VoicedClip, voice_clip
from ...audio.voice.timing import merge_windows, speech_windows
from ...config import AudioCfg
from ...eval.metrics.dialogue import ScriptedLine, match_dialogue
from ...schemas.stems import StemMix
from ...schemas.voice import VoiceProfile
from .contracts import ClipCase, ClipEval, LineEval, Variant
from .judge import judge_mix
from .metrics import bed_lag_ms, decode_pcm, median_f0, outside_level_db
from .retry import with_backoff

logger = logging.getLogger(__name__)
COMPLETE_SIM = 0.8


def _line_evals(
    case: ClipCase, vc: VoicedClip, voiced_t: Transcript, voiced_path: Path
) -> list[LineEval]:
    scripted = [ScriptedLine(ln.speaker_name, ln.lang, ln.text) for ln in case.lines]
    matches = match_dialogue(scripted, voiced_t).lines
    orig_x, voiced_x = decode_pcm(case.path), decode_pcm(voiced_path)
    out: list[LineEval] = []
    for ln, m, placed in zip(case.lines, matches, vc.lines, strict=True):
        seg = m.segment
        out.append(
            LineEval(
                line_id=ln.line_id,
                speaker_id=ln.speaker_id,
                text=ln.text,
                voiced_similarity=round(m.similarity, 3),
                heard_complete=m.similarity >= COMPLETE_SIM,
                onset_offset_s=None
                if seg is None or placed.estimated_slot
                else round(seg.t_start - placed.slot_start_s, 3),
                orig_f0_hz=median_f0(orig_x, (placed.slot_start_s, placed.slot_end_s)),
                voiced_f0_hz=median_f0(
                    voiced_x, (placed.placed_start_s, placed.placed_end_s)
                ),
            )
        )
    return out


def evaluate_clip(
    case: ClipCase,
    remover: Variant,
    vc: VoicedClip,
    voiced_path: Path,
    transcriber: Transcriber,
    runtime_s: float,
) -> ClipEval:
    names = sorted({ln.speaker_name for ln in case.lines})
    voiced_t = transcriber.transcribe(
        vc.video, names, sorted({ln.lang for ln in case.lines})
    )
    windows = merge_windows(
        speech_windows(vc.transcript, [])
        + [(p.placed_start_s, p.placed_end_s) for p in vc.lines]
    )
    scripted = [ScriptedLine(ln.speaker_name, ln.lang, ln.text) for ln in case.lines]
    return ClipEval(
        clip_id=case.clip_id,
        remover=remover,
        voiced_path=str(voiced_path),
        runtime_s=round(runtime_s, 2),
        lines=_line_evals(case, vc, voiced_t, voiced_path),
        placements=vc.lines,
        bed_orig_db=outside_level_db(decode_pcm(case.path), windows),
        bed_voiced_db=outside_level_db(decode_pcm(voiced_path), windows),
        sfx_lag_ms=bed_lag_ms(decode_pcm(case.path), decode_pcm(voiced_path), windows),
        extra_speech=[s.text for s in match_dialogue(scripted, voiced_t).extra],
        mix=with_backoff(lambda: judge_mix(vc.video), "judge_mix"),
    )


def _stems_clip(
    case: ClipCase, voices: dict[str, VoiceProfile], deps: SyncDeps
) -> VoicedClip:
    """audio.mode=stems: guide-timed TTS dialogue stem + demucs SFX stem, no Omni voice."""
    clip = case.path.read_bytes()
    cfg = AudioCfg(mode="stems")
    sfx = DemucsSfx(residual_db=cfg.residual_db, media=deps.media)
    built = build_stems(
        clip, case.lines, voices, cfg, StemDeps(deps, sfx), case.clip_id
    )
    mix = StemMix(dialogue_uri="", sfx_uri="")
    tools = RenderTools(media=deps.media)
    video = render_stem_clip(clip, StemAudio(built.dialogue, built.sfx), mix, tools)
    return VoicedClip(video, built.lines, built.transcript, "duck")


def _variant_clip(
    case: ClipCase, voices: dict[str, VoiceProfile], name: Variant, deps: SyncDeps
) -> VoicedClip:
    if name == "stems":
        return _stems_clip(case, voices, deps)
    cfg = AudioCfg(mode="voiceover_duck", speech_removal=name)
    return voice_clip(
        case.path.read_bytes(), case.lines, voices, cfg, deps, case.clip_id
    )


def run_case(
    case: ClipCase,
    voices: dict[str, VoiceProfile],
    deps_by_remover: dict[Variant, SyncDeps],
    out_dir: Path,
) -> list[ClipEval]:
    """Voice one clip with every remover; save `<out>/<remover>/<clip>.mp4` and evaluate."""
    evals: list[ClipEval] = []
    for name, deps in deps_by_remover.items():
        started = time.monotonic()
        vc = _variant_clip(case, voices, name, deps)
        runtime = time.monotonic() - started
        path = out_dir / name / f"{case.clip_id}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(vc.video)
        evals.append(evaluate_clip(case, name, vc, path, deps.transcriber, runtime))
        logger.info(
            "Experiment clip voiced",
            extra=log_ctx(
                "experiments.voiceover_sync.runner",
                "experiment_clip_voiced",
                "voiceover_sync_v1 before/after comparison",
                f"voice_clip with {name} speech removal",
                clip_id=case.clip_id,
                runtime_s=round(runtime, 2),
            ),
        )
    return evals
