"""Typed outcomes of a governed GenAI call (all `StoryGraphError`s, so stage isolation sees them)."""

from __future__ import annotations

from ...errors import StoryGraphError


class EmptyModelResponse(StoryGraphError):
    """The model answered without the requested modality (e.g. text instead of an image).

    Stochastic, so the governor retries it a few times (`max_empty_retries`) without treating
    it as a quota signal."""


class ModelCallError(StoryGraphError):
    """A governed call gave up; carries model, attempt count and elapsed seconds."""

    reason: str = "model call failed"

    def __init__(self, model: str, attempts: int, elapsed_s: float, cause: str) -> None:
        self.model, self.attempts, self.elapsed_s = model, attempts, elapsed_s
        self.cause = cause
        super().__init__(
            f"{self.reason} after {attempts} attempt(s) over {elapsed_s:.0f}s "
            f"({model}): {cause[:240]}"
        )


class QuotaExhausted(ModelCallError):
    """429 / RESOURCE_EXHAUSTED persisted for the whole retry budget."""

    reason = "quota exhausted"


class TransientModelError(ModelCallError):
    """5xx / UNAVAILABLE / DEADLINE_EXCEEDED / network errors persisted for the whole budget."""

    reason = "model unavailable"


class GovernorSaturated(TransientModelError):
    """The per-model FIFO queue was full or the queue wait exceeded the retry budget."""

    reason = "call queue saturated"
