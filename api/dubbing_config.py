"""Dubbing configuration — the single place every DUBBING_* env var is read.

Kept separate from the modules that use it so the router (validation, language
picker) and the worker (session tuning) share one source of truth, and so tests
can exercise the guards without importing the Live client or ffmpeg.

Values are read per call rather than cached at import: the worker is a
long-lived process and a Cloud Run revision rollout should not require code
changes to take effect.
"""

import os

from models_records import DUB_LANGUAGES

# Wire constants — fixed by the Live API contract, not configurable.
# Verified against gemini-3.5-live-translate-preview: input must be 16 kHz mono
# s16le, output arrives as 24 kHz mono s16le.
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2
CHUNK_MS = 100

LIVE_URI = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)

DEFAULT_MODEL = "gemini-3.5-live-translate-preview"


def live_model() -> str:
    return os.getenv("DUBBING_LIVE_MODEL", DEFAULT_MODEL)


def live_surface() -> str:
    """`developer` (API key) or `vertex`. Live Translate is Developer-API-only
    today; the switch exists so moving to Vertex is config, not a rewrite."""
    return os.getenv("DUBBING_LIVE_SURFACE", "developer")


def api_key() -> str:
    """Never log or persist the return value. Raises rather than sending an
    unauthenticated request that would fail confusingly downstream."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set — required for the dubbing Live session"
        )
    return key


def supported_languages() -> dict[str, str]:
    """Active target languages: the DUBBING_LANGUAGES env subset of the
    DUB_LANGUAGES allowlist. An unknown code in the env var is ignored rather
    than trusted, so the env can never widen the allowlist."""
    raw = os.getenv("DUBBING_LANGUAGES", "")
    codes = [c.strip() for c in raw.split(",") if c.strip()]
    active = {c: DUB_LANGUAGES[c] for c in codes if c in DUB_LANGUAGES}
    return active or dict(DUB_LANGUAGES)


def window_sec() -> int:
    """Session length cap. Live sessions are limited to 15 minutes audio-only;
    600 s leaves headroom for the post-stream drain."""
    return int(os.getenv("DUBBING_WINDOW_SEC", "600"))


def pace() -> float:
    """Input stream rate relative to realtime. 1.0 measured best for alignment;
    2.0 works but pushes interpreter lag from ~3.4 s to ~4.7 s."""
    return float(os.getenv("DUBBING_PACE", "1.0"))


def silence_stop_sec() -> float:
    """The model emits no completion flag — after translating it streams silent
    keep-alive audio indefinitely. Draining stops after this much continuous
    silence, which is the only reliable end-of-content signal."""
    return float(os.getenv("DUBBING_SILENCE_STOP_SEC", "4.0"))


def silence_floor_db() -> float:
    return float(os.getenv("DUBBING_SILENCE_FLOOR_DB", "-60.0"))


def max_source_minutes() -> float:
    """Resource guard: the worker runs single-instance, single-job, so a long
    source blocks every other job for its whole duration."""
    return float(os.getenv("DUBBING_MAX_SOURCE_MINUTES", "30"))


def max_languages() -> int:
    return int(os.getenv("DUBBING_MAX_LANGUAGES", "4"))
