"""Prompt and schema resolution for AI service methods."""

import json
import logging
from collections import defaultdict

from ai_helpers import load_schema, resolve_resource
from prompt_templates import DEFAULT_BRIEF_PROMPT, default_promo_prompt

logger = logging.getLogger(__name__)

CATEGORY_MAP = {
    "movie": "production-movie",
    "advertizement": "production-ad",
    "social": "production-social",
}


def gcs_ref_url(project) -> str | None:
    """Return GCS reference image URL if available, else None."""
    url = project.reference_image_url if project else None
    return url if url and url.startswith("gs://") else None


LANGUAGE_BRIEF_DIRECTIVES = {
    "hi-IN": (
        "AUDIO & VOICE-OVER LANGUAGE: Hindi (hi-IN, हिन्दी). Write every scene's "
        "`narration` (voice-over or spoken dialogue) in natural, expressive Hindi "
        "(Devanagari script) matched to the scene duration. Keep `visual_description`, "
        "`metadata`, and `music_description` in English."
    ),
    "en-IN": (
        "AUDIO & VOICE-OVER LANGUAGE: English (India) (en-IN). Write every scene's "
        "`narration` (voice-over or spoken dialogue) in natural Indian English "
        "phrasing and cadence, intended for an Indian English voice-over accent."
    ),
    "en-US": "AUDIO & VOICE-OVER LANGUAGE: English (US) (en-US).",
}


def _duration_directive(length: str) -> str:
    try:
        total_sec = int(length)
    except (TypeError, ValueError):
        return ""
    if total_sec <= 0:
        return ""
    scene_count = max(2, round(total_sec / 8))
    mins, secs = divmod(total_sec, 60)
    end_ts = f"{mins:02d}:{secs:02d}"
    return (
        f"\nSTRICT DURATION REQUIREMENT: Total video runtime MUST be exactly {total_sec} seconds "
        f"(00:00 to {end_ts}), structured as {scene_count} contiguous scenes of ~8 seconds each "
        f"(e.g. 00:00-00:08, 00:08-00:16, ... up to {end_ts})."
    )


class PromptResolver:
    """Resolves prompts and schemas from Firestore or defaults."""

    def __init__(self, firestore_svc=None):
        self.firestore_svc = firestore_svc

    def require_prompt(self, prompt_id: str) -> str:
        """Load a prompt from Firestore, raising if not found."""
        if not self.firestore_svc:
            raise ValueError("Firestore service not available")
        res = self.firestore_svc.get_resource(prompt_id)
        if not res:
            raise ValueError(f"Prompt resource not found: {prompt_id}")
        return res.content

    def resolve_schema(self, schema_id, category, default_name) -> dict:
        """Resolve JSON schema from Firestore or load default."""
        if self.firestore_svc:
            content = resolve_resource(
                self.firestore_svc, schema_id or "", "schema", category
            )
            if content:
                return json.loads(content)
        return load_schema(default_name)

    def resolve_brief_prompt(
        self, concept, length, orientation, prompt_id, project_type, project
    ) -> str:
        """Resolve and format the brief analysis prompt."""
        template = self._lookup_brief_template(prompt_id, project_type)
        ref_note = (
            "A reference image is attached above — use it as a visual style guide."
            if gcs_ref_url(project)
            else ""
        )
        lang_code = getattr(project, "language", None) or "en-IN"
        lang_note = LANGUAGE_BRIEF_DIRECTIVES.get(
            lang_code, LANGUAGE_BRIEF_DIRECTIVES["en-IN"]
        )
        formatted = template.format_map(
            defaultdict(
                str,
                length=length,
                orientation=orientation,
                concept=concept,
                ref_images=ref_note,
                language=lang_code,
            )
        )
        return f"{formatted}\n{_duration_directive(length)}\n{lang_note}"

    def _lookup_brief_template(self, prompt_id, project_type) -> str:
        """Resolve template: explicit ID > category > default."""
        if not self.firestore_svc:
            return DEFAULT_BRIEF_PROMPT
        if prompt_id:
            return (
                resolve_resource(self.firestore_svc, prompt_id) or DEFAULT_BRIEF_PROMPT
            )
        category = CATEGORY_MAP.get(project_type, "production-ad")
        return (
            resolve_resource(self.firestore_svc, "", "prompt", category)
            or DEFAULT_BRIEF_PROMPT
        )

    def resolve_promo_prompt(self, prompt_id: str, target_duration: int) -> str:
        """Resolve promo prompt with variable substitution."""
        content = (
            resolve_resource(self.firestore_svc, prompt_id, "prompt", "promo")
            if self.firestore_svc
            else None
        )
        if content:
            return content.replace("{target_duration}", str(target_duration))
        return default_promo_prompt(target_duration)
