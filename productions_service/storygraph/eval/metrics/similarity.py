"""Embedding similarity of clip frames vs labelled references and the previous clip's end."""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image

from ...adapters.embeddings import ImageEmbedder, cosine
from ...adapters.media_frames import TimedFrame
from ..contracts import LabelledRef

MAX_FRAMES = 8
CENTER_CROP = 0.6


@dataclass(frozen=True)
class SimilarityMetrics:
    """Max frame similarity per reference label (identity) plus setting / seam similarity."""

    identity: dict[str, float] = field(default_factory=dict)
    setting: float | None = None
    prev_seam: float | None = None
    confidence: float = 0.0
    embedder: str = ""


def _center_crop(png: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(png)).convert("RGB")
    except (OSError, ValueError):
        return png
    w, h = img.size
    dw, dh = int(w * (1 - CENTER_CROP) / 2), int(h * (1 - CENTER_CROP) / 2)
    buf = io.BytesIO()
    img.crop((dw, dh, w - dw, h - dh)).save(buf, format="PNG")
    return buf.getvalue()


def _sample(frames: list[TimedFrame]) -> list[bytes]:
    """Up to MAX_FRAMES evenly spaced frames (first and last included)."""
    if len(frames) <= MAX_FRAMES:
        return [f.png for f in frames]
    step = (len(frames) - 1) / (MAX_FRAMES - 1)
    return [frames[round(i * step)].png for i in range(MAX_FRAMES)]


def _best(vecs: list[list[float]], ref: list[float]) -> float:
    return round(max((cosine(v, ref) for v in vecs), default=0.0), 3)


def compute_similarity(
    embedder: ImageEmbedder,
    frames: list[TimedFrame],
    refs: list[LabelledRef],
    prev_last_frame: bytes | None,
) -> SimilarityMetrics:
    """Embed sampled frames (full + centre crop) once, then compare against every reference."""
    pngs = _sample(frames)
    if not pngs:
        return SimilarityMetrics(embedder=embedder.name)
    full = [embedder.embed(p) for p in pngs]
    crops = [embedder.embed(_center_crop(p)) for p in pngs]
    identity = {
        r.label: _best(full + crops, embedder.embed(r.png))
        for r in refs
        if r.kind == "identity"
    }
    settings = [_best(full, embedder.embed(r.png)) for r in refs if r.kind == "setting"]
    seam = cosine(full[0], embedder.embed(prev_last_frame)) if prev_last_frame else None
    return SimilarityMetrics(
        identity=identity,
        setting=max(settings) if settings else None,
        prev_seam=round(seam, 3) if seam is not None else None,
        confidence=embedder.confidence,
        embedder=embedder.name,
    )
