"""Shared helpers for Gemini-based AI service methods.

Eliminates repeated patterns: schema loading, cost calculation,
image extraction/upload, and Firestore resource resolution.
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from models import UsageMetrics

logger = logging.getLogger(__name__)

# Gemini pricing per token (as of 2025)
_INPUT_COST = 0.000002
_OUTPUT_COST = 0.000012
_IMAGE_GEN_COST = 0.134


def load_schema(name: str) -> dict:
    """Load a JSON schema from the schemas/ directory by name."""
    path = Path(__file__).parent / "schemas" / f"{name}.json"
    return json.loads(path.read_text())


def compute_usage(response, model_id: str) -> UsageMetrics:
    """Build UsageMetrics from a Gemini response."""
    meta = response.usage_metadata
    return UsageMetrics(
        input_tokens=meta.prompt_token_count,
        output_tokens=meta.candidates_token_count,
        model_name=model_id,
        cost_usd=(meta.prompt_token_count * _INPUT_COST)
        + (meta.candidates_token_count * _OUTPUT_COST),
    )


def image_generation_usage(model_id: str) -> UsageMetrics:
    """UsageMetrics for image generation (flat cost, no token counts)."""
    return UsageMetrics(model_name=model_id, cost_usd=_IMAGE_GEN_COST)


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
