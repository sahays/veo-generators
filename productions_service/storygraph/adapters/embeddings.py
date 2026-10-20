"""Image embedding adapters for identity/setting similarity (Vertex multimodal or histogram).

`VertexImageEmbedder` uses `multimodalembedding@001` (cached by content digest). When Vertex is
unavailable, `HistogramEmbedder` provides a colour-histogram vector with LOW confidence so the
eval degrades gracefully instead of failing.
"""

from __future__ import annotations

import io
import logging
import math
from datetime import UTC, datetime
from typing import Protocol

from PIL import Image

from .bounded_cache import BoundedCache, digest

logger = logging.getLogger(__name__)

_HIST_BINS = 4


class ImageEmbedder(Protocol):
    """Maps a PNG to a vector; `confidence` says how identity-discriminative it is."""

    confidence: float
    name: str

    def embed(self, png: bytes) -> list[float]: ...


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1] (0.0 for empty / zero vectors)."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class HistogramEmbedder:
    """Normalized 4x4x4 RGB histogram (palette similarity only; low confidence)."""

    confidence = 0.35
    name = "rgb-histogram"

    def embed(self, png: bytes) -> list[float]:
        try:
            img = Image.open(io.BytesIO(png)).convert("RGB").resize((64, 64))
        except (OSError, ValueError):
            return []
        step = 256 // _HIST_BINS
        counts = [0.0] * (_HIST_BINS**3)
        for r, g, b in img.getdata():
            counts[
                (r // step) * _HIST_BINS**2 + (g // step) * _HIST_BINS + b // step
            ] += 1
        total = sum(counts) or 1.0
        return [c / total for c in counts]


class VertexImageEmbedder:
    """Vertex AI multimodal image embeddings with an in-process LRU cache."""

    confidence = 0.8
    name = "multimodalembedding@001"

    def __init__(
        self, project: str | None = None, location: str = "us-central1"
    ) -> None:
        import vertexai
        from vertexai.vision_models import MultiModalEmbeddingModel

        vertexai.init(project=project, location=location)
        self._model = MultiModalEmbeddingModel.from_pretrained(self.name)
        self._cache: BoundedCache[list[float]] = BoundedCache(512)

    def embed(self, png: bytes) -> list[float]:
        from vertexai.vision_models import Image as VImage

        key = digest(png, self.name)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        vec = list(self._model.get_embeddings(image=VImage(png)).image_embedding or [])
        self._cache.put(key, vec)
        return vec


def make_embedder(prefer_vertex: bool, project: str | None = None) -> ImageEmbedder:
    """Vertex embedder when requested and constructible, else the histogram fallback."""
    if prefer_vertex:
        try:
            return VertexImageEmbedder(project=project)
        except Exception as exc:  # noqa: BLE001 - SDK/auth errors are untyped
            logger.warning(
                "Vertex embedder unavailable; using histogram fallback",
                extra={
                    "who": "storygraph.adapters.embeddings",
                    "where": "embeddings.make_embedder",
                    "what": "embedder_fallback",
                    "when": datetime.now(UTC).isoformat(),
                    "why": str(exc)[:200],
                    "how": "VertexImageEmbedder construction failed",
                },
            )
    return HistogramEmbedder()
