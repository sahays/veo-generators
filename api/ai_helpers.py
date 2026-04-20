"""Shared helpers for Gemini-based AI service methods.

Eliminates repeated patterns: schema loading, cost calculation,
image extraction/upload, and Firestore resource resolution.
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from models import UsageMetrics
from pricing_config import cost_for_image, cost_for_text

logger = logging.getLogger(__name__)


def resolve_model(
    firestore_svc,
    capability: str,
    env_var: str,
    env_default: str,
    model_id: Optional[str] = None,
) -> str:
    """Resolve model: explicit param > Firestore default > env var."""
    if model_id:
        return model_id
    if firestore_svc:
        default = firestore_svc.get_default_model(capability)
        if default:
            return default.code
    return os.getenv(env_var, env_default)


def load_schema(name: str) -> dict:
    """Load a JSON schema from the schemas/ directory by name."""
    path = Path(__file__).parent / "schemas" / f"{name}.json"
    return json.loads(path.read_text())


def compute_usage(response, model_id: str) -> UsageMetrics:
    """Build UsageMetrics from a Gemini text response using tier-aware pricing."""
    meta = response.usage_metadata
    input_tokens = meta.prompt_token_count or 0
    output_tokens = meta.candidates_token_count or 0
    return UsageMetrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_name=model_id,
        cost_usd=cost_for_text(model_id, input_tokens, output_tokens),
    )


def compute_image_usage(response, model_id: str) -> UsageMetrics:
    """UsageMetrics for a Gemini image response using real token counts.

    Image models are priced per output token (not per-image). A standard
    1024×1024 image is ~1,290 output tokens at $60/1M = ~$0.0774/image.
    """
    meta = response.usage_metadata
    input_tokens = meta.prompt_token_count or 0
    output_tokens = meta.candidates_token_count or 0
    image_cost = cost_for_image(model_id, 0, output_tokens)
    total_cost = cost_for_image(model_id, input_tokens, output_tokens)
    return UsageMetrics(
        model_name=model_id,
        image_model_name=model_id,
        cost_usd=total_cost,
        image_generations=1,
        image_input_tokens=input_tokens,
        image_output_tokens=output_tokens,
        image_cost_usd=image_cost,
    )


def image_generation_usage(model_id: str) -> UsageMetrics:
    """Deprecated stub — retained for callers migrating to compute_image_usage.

    Returns a zero-cost UsageMetrics so legacy call sites don't over-bill.
    """
    logger.warning(
        "image_generation_usage is deprecated; use compute_image_usage(response, model_id)"
    )
    return UsageMetrics(model_name=model_id, cost_usd=0.0, image_generations=1)


def extract_image_from_response(
    response,
    storage_svc,
    dest_folder: str,
) -> str:
    """Extract inline image from Gemini response and upload to GCS.

    Returns the uploaded image URL. Raises ValueError if no image found.
    """
    if response.candidates and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                if not storage_svc:
                    raise ValueError("Storage service not available")
                dest = f"{dest_folder}/{uuid.uuid4()}.png"
                return storage_svc.upload_bytes(part.inline_data.data, dest)
    raise ValueError("Response produced no image")


def resolve_resource(
    firestore_svc,
    resource_id: str,
    resource_type: str = "prompt",
    category: Optional[str] = None,
) -> Optional[str]:
    """Resolve a resource from Firestore by ID or active category.

    Returns the resource content string, or None if not found.
    """
    if not firestore_svc:
        return None
    if resource_id:
        res = firestore_svc.get_resource(resource_id)
        if res:
            return res.content
    if category:
        res = firestore_svc.get_active_resource(resource_type, category)
        if res:
            return res.content
    return None
