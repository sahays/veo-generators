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
        return template.format_map(
            defaultdict(
                str,
                length=length,
                orientation=orientation,
                concept=concept,
                ref_images=ref_note,
            )
        )

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
