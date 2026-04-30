"""Single source of truth for service pricing.

All hardcoded rates must live here. Verified against Google Cloud pricing
pages in April 2026. See docstring on each rate for the source.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TokenTier:
    """A tiered per-token rate. `threshold_tokens` is the input-context cutoff;
    if input tokens <= threshold, this tier applies. None = no cutoff (default)."""

    threshold_tokens: Optional[int]
    input_per_token: float
    output_per_token: float


@dataclass(frozen=True)
class TextModelRate:
    model_id: str
    label: str
    tiers: tuple  # tuple[TokenTier, ...] — first matching tier wins


@dataclass(frozen=True)
class ImageModelRate:
    """Image model priced per output token (not per-image)."""

    model_id: str
    label: str
    input_per_token: float
    output_per_token: float


@dataclass(frozen=True)
class FlatRate:
    id: str
    label: str
    unit: str  # "second" | "minute"
    unit_cost_usd: float


# ---------------------------------------------------------------------------
# Gemini text models (source: cloud.google.com/vertex-ai/generative-ai/pricing)
# ---------------------------------------------------------------------------

GEMINI_PRO_31 = TextModelRate(
    model_id="gemini-3.1-pro-preview",
    label="Gemini 3.1 Pro",
    tiers=(
        TokenTier(
            threshold_tokens=200_000, input_per_token=2e-6, output_per_token=12e-6
        ),
        TokenTier(threshold_tokens=None, input_per_token=4e-6, output_per_token=18e-6),
    ),
)

GEMINI_PRO_3 = TextModelRate(
    model_id="gemini-3-pro-preview",
    label="Gemini 3 Pro",
    tiers=(
        TokenTier(
            threshold_tokens=200_000, input_per_token=2e-6, output_per_token=12e-6
        ),
        TokenTier(threshold_tokens=None, input_per_token=4e-6, output_per_token=18e-6),
    ),
)

GEMINI_FLASH_3 = TextModelRate(
    model_id="gemini-3-flash-preview",
    label="Gemini 3 Flash",
    tiers=(
        TokenTier(threshold_tokens=None, input_per_token=0.5e-6, output_per_token=3e-6),
    ),
)

GEMINI_FLASH_LITE_31 = TextModelRate(
    model_id="gemini-3.1-flash-lite-preview",
    label="Gemini 3.1 Flash Lite",
    tiers=(
        TokenTier(
            threshold_tokens=None, input_per_token=0.25e-6, output_per_token=1.5e-6
        ),
    ),
)

GEMINI_25_PRO = TextModelRate(
    model_id="gemini-2.5-pro",
    label="Gemini 2.5 Pro",
    tiers=(
        TokenTier(
            threshold_tokens=200_000, input_per_token=1.25e-6, output_per_token=10e-6
        ),
        TokenTier(
            threshold_tokens=None, input_per_token=2.5e-6, output_per_token=15e-6
        ),
    ),
)

GEMINI_25_FLASH = TextModelRate(
    model_id="gemini-2.5-flash",
    label="Gemini 2.5 Flash",
    tiers=(
        TokenTier(
            threshold_tokens=None, input_per_token=0.3e-6, output_per_token=2.5e-6
        ),
    ),
)

GEMINI_25_FLASH_LITE = TextModelRate(
    model_id="gemini-2.5-flash-lite",
    label="Gemini 2.5 Flash Lite",
    tiers=(
        TokenTier(
            threshold_tokens=None, input_per_token=0.1e-6, output_per_token=0.4e-6
        ),
    ),
)


# ---------------------------------------------------------------------------
# Gemini image model (token-based — $60 per 1M image-output tokens)
# ---------------------------------------------------------------------------

GEMINI_FLASH_IMAGE_31 = ImageModelRate(
    model_id="gemini-3.1-flash-image-preview",
    label="Gemini 3.1 Flash Image",
    input_per_token=0.5e-6,
    output_per_token=60e-6,
)


# ---------------------------------------------------------------------------
# Veo video models
# ---------------------------------------------------------------------------

VEO_STANDARD = FlatRate("veo_standard", "Veo 3.1 Standard", "second", 0.40)
VEO_FAST = FlatRate("veo_fast", "Veo 3.1 Fast", "second", 0.15)
VEO_LITE = FlatRate("veo_lite", "Veo 3.1 Lite", "second", 0.05)

VEO_BY_MODEL: dict[str, FlatRate] = {
    "veo-3.1-generate-001": VEO_STANDARD,
    "veo-3.1-fast-generate-001": VEO_FAST,
    "veo-3.1-lite-generate-001": VEO_LITE,
}


# ---------------------------------------------------------------------------
# Flat services (Cloud Transcoder, Speech V2 / Chirp 3)
# ---------------------------------------------------------------------------

TRANSCODER_SD = FlatRate("transcoder_sd", "Cloud Transcoder (SD)", "minute", 0.015)
TRANSCODER_HD = FlatRate(
    "transcoder_hd", "Cloud Transcoder (HD 1080p)", "minute", 0.030
)
TRANSCODER_4K = FlatRate("transcoder_4k", "Cloud Transcoder (4K)", "minute", 0.060)
TRANSCODER_AUDIO = FlatRate(
    "transcoder_audio", "Cloud Transcoder (audio-only)", "minute", 0.005
)

DIARIZATION = FlatRate("diarization", "Speech V2 (Chirp 3)", "minute", 0.016)


# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------

TEXT_MODELS: dict[str, TextModelRate] = {
    m.model_id: m
    for m in (
        GEMINI_PRO_31,
        GEMINI_PRO_3,
        GEMINI_FLASH_3,
        GEMINI_FLASH_LITE_31,
        GEMINI_25_PRO,
        GEMINI_25_FLASH,
        GEMINI_25_FLASH_LITE,
    )
}

IMAGE_MODELS: dict[str, ImageModelRate] = {
    m.model_id: m for m in (GEMINI_FLASH_IMAGE_31,)
}

FLAT_SERVICES: dict[str, FlatRate] = {
    r.id: r
    for r in (
        TRANSCODER_SD,
        TRANSCODER_HD,
        TRANSCODER_4K,
        TRANSCODER_AUDIO,
        DIARIZATION,
    )
}


# ---------------------------------------------------------------------------
# Feature → services consumed. Drives the "Services used" UI and estimator.
# ---------------------------------------------------------------------------

FEATURE_SERVICES: dict[str, list[str]] = {
    "production": ["gemini_text", "gemini_image", "veo", "transcoder"],
    "adapts": ["gemini_image"],
    "reframe": ["gemini_text", "diarization", "transcoder"],
    "promo": [
        "gemini_text",
        "gemini_image",
    ],  # stitching is local ffmpeg, no transcoder
    "key_moments": ["gemini_text"],
    "thumbnails": ["gemini_text", "gemini_image"],
}


# ---------------------------------------------------------------------------
# Estimator hints — rough token counts per feature for the pre-run estimator.
# Sourced from historical averages; document as "estimates, not guarantees".
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EstimatorHints:
    # Per-call Gemini usage averages
    production_analyze_input_tokens: int = 3_000
    production_analyze_output_tokens: int = 2_500
    reframe_analyze_input_tokens: int = 8_000
    reframe_analyze_output_tokens: int = 1_200
    promo_segment_input_tokens: int = 4_000
    promo_segment_output_tokens: int = 1_500
    key_moments_input_tokens: int = 6_000
    key_moments_output_tokens: int = 1_800
    thumbnails_analyze_input_tokens: int = 5_000
    thumbnails_analyze_output_tokens: int = 1_500
    # Image output
    image_output_tokens: int = 1_290  # standard 1024x1024 Gemini image
    image_input_tokens: int = 400  # reference image + prompt
    # Veo durations are supplied by the request (scene_count * 8s typical)


HINTS = EstimatorHints()


# ---------------------------------------------------------------------------
# Default model choices per capability (for the estimator when request omits).
# Kept in sync with Dockerfile / .env.example defaults.
# ---------------------------------------------------------------------------

DEFAULT_TEXT_MODEL = "gemini-3.1-pro-preview"
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image-preview"
DEFAULT_VIDEO_MODEL = "veo-3.1-generate-001"
DEFAULT_TRANSCODER_TIER = TRANSCODER_HD


# ---------------------------------------------------------------------------
# Cost computation helpers
# ---------------------------------------------------------------------------


def cost_for_text(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Tier-aware per-model cost for a Gemini text response.

    Unknown model IDs fall back to Pro rates (conservative over-estimate).
    """
    rate = TEXT_MODELS.get(model_id) or GEMINI_PRO_31
    for tier in rate.tiers:
        if tier.threshold_tokens is None or input_tokens <= tier.threshold_tokens:
            return (
                input_tokens * tier.input_per_token
                + output_tokens * tier.output_per_token
            )
    # Unreachable: the last tier always has threshold_tokens=None.
    last = rate.tiers[-1]
    return input_tokens * last.input_per_token + output_tokens * last.output_per_token


def cost_for_image(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Token-based image cost. Replaces the legacy flat per-image constant."""
    rate = IMAGE_MODELS.get(model_id) or GEMINI_FLASH_IMAGE_31
    return input_tokens * rate.input_per_token + output_tokens * rate.output_per_token


def cost_for_veo(model_id: str, seconds: float) -> float:
    rate = VEO_BY_MODEL.get(model_id) or VEO_STANDARD
    return seconds * rate.unit_cost_usd


def veo_rate_for(model_id: str) -> FlatRate:
    return VEO_BY_MODEL.get(model_id) or VEO_STANDARD


def cost_for_flat(service_id: str, units: float) -> float:
    rate = FLAT_SERVICES.get(service_id)
    if not rate:
        return 0.0
    return units * rate.unit_cost_usd
