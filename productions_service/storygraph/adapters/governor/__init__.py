"""Process-wide GenAI call governor: per-model FIFO queue + AIMD token bucket + one retry policy."""

from .context import call_scope, current_scope
from .errors import (
    EmptyModelResponse,
    GovernorSaturated,
    ModelCallError,
    QuotaExhausted,
    TransientModelError,
)
from .governor import Governor
from .registry import default_governor, governed, use_governor

__all__ = [
    "EmptyModelResponse",
    "Governor",
    "GovernorSaturated",
    "ModelCallError",
    "QuotaExhausted",
    "TransientModelError",
    "call_scope",
    "current_scope",
    "default_governor",
    "governed",
    "use_governor",
]
