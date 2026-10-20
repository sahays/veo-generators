"""All deterministic metrics for one clip, computed once and shared by every dimension."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ...adapters.audio_levels import AudioLevels, measure_audio_levels
from ...adapters.embeddings import ImageEmbedder
from ...adapters.media_frames import ClipProbe
from ...adapters.transcribe import Transcriber, Transcript
from ...errors import StoryGraphError
from ..contracts import EvalInput
from .dialogue import DialogueMatch, ScriptedLine, match_dialogue
from .similarity import SimilarityMetrics, compute_similarity
from .video import VideoMetrics, compute_video_metrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricBundle:
    """Shared, VLM-free measurements (fields are empty/None when unavailable)."""

    probe: ClipProbe
    video: VideoMetrics = field(default_factory=VideoMetrics)
    audio: AudioLevels | None = None
    similarity: SimilarityMetrics = field(default_factory=SimilarityMetrics)
    lines: list[ScriptedLine] = field(default_factory=list)
    transcript: Transcript = field(default_factory=lambda: Transcript(available=False))
    dialogue: DialogueMatch | None = None


def scripted_lines(spec: dict[str, Any]) -> list[ScriptedLine]:
    """Spoken lines in script order with speaker ids resolved to subject names."""
    names = {
        str(s.get("id")): str(s.get("name") or s.get("id"))
        for s in spec.get("subjects") or []
        if isinstance(s, dict)
    }
    return [
        ScriptedLine(
            speaker=names.get(str(ln.get("speaker")), str(ln.get("speaker") or "")),
            lang=str(ln.get("lang") or ""),
            text=str(ln.get("text") or ""),
        )
        for ln in spec.get("speech") or []
        if isinstance(ln, dict) and ln.get("text")
    ]


def _log_degraded(what: str, why: str, how: str, shot_id: str) -> None:
    logger.warning(
        "Eval metric degraded",
        extra={
            "who": "storygraph.eval.metrics.bundle",
            "where": "bundle.compute_metrics",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why[:200],
            "how": how,
            "shot_id": shot_id,
        },
    )


def _safe_similarity(
    embedder: ImageEmbedder, probe: ClipProbe, inp: EvalInput
) -> SimilarityMetrics:
    """Embedding similarity; any embedder/network failure degrades to 'unavailable'."""
    try:
        return compute_similarity(embedder, probe.frames, inp.refs, inp.prev_last_frame)
    except Exception as exc:  # noqa: BLE001 - SDK/network errors are untyped
        _log_degraded("similarity_unavailable", str(exc), embedder.name, inp.shot_id)
        return SimilarityMetrics()


def _transcribe(
    transcriber: Transcriber | None,
    clip: bytes,
    lines: list[ScriptedLine],
    shot_id: str,
) -> Transcript:
    if transcriber is None or not clip:
        return Transcript(available=False)
    speakers = sorted({ln.speaker for ln in lines})
    langs = sorted({ln.lang for ln in lines if ln.lang})
    try:
        return transcriber.transcribe(clip, speakers, langs)
    except StoryGraphError as exc:
        _log_degraded(
            "transcription_unavailable", str(exc), type(transcriber).__name__, shot_id
        )
        return Transcript(available=False)


def compute_metrics(
    inp: EvalInput,
    probe: ClipProbe,
    embedder: ImageEmbedder | None,
    transcriber: Transcriber | None,
) -> MetricBundle:
    """Run every deterministic metric once (decoded clips only; synthetic probes skip)."""
    spec = inp.spec_dict()
    clip_spec = spec.get("clip") if isinstance(spec.get("clip"), dict) else {}
    lines = scripted_lines(spec)
    decoded = probe.duration_s > 0.0
    clip = inp.load_clip() if decoded else b""
    sim = (
        _safe_similarity(embedder, probe, inp)
        if embedder is not None and decoded
        else SimilarityMetrics()
    )
    transcript = _transcribe(transcriber, clip, lines, inp.shot_id)
    return MetricBundle(
        probe=probe,
        video=compute_video_metrics(probe, float(clip_spec.get("duration_s") or 0.0)),
        audio=measure_audio_levels(clip) if decoded else None,
        similarity=sim,
        lines=lines,
        transcript=transcript,
        dialogue=match_dialogue(lines, transcript) if transcript.available else None,
    )
