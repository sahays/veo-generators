"""Prompt-format dispatch: the one place an `OmniClipSpec` becomes the text sent to Omni.

`hybrid` (default, `video.prompt_format` in `config/default.yaml`) is the V3 winner of the
prompt-format A/B; `json` is the legacy compact spec JSON, kept switchable for future A/Bs.
"""

from __future__ import annotations

from typing import Final

from pydantic import ValidationError

from .render_hybrid import render_hybrid
from .spec import OmniClipSpec, PromptFormat

DEFAULT_PROMPT_FORMAT: Final[PromptFormat] = "hybrid"


def render_prompt(spec: OmniClipSpec, fmt: PromptFormat) -> str:
    """Deterministic Omni prompt text for `spec` in `fmt`."""
    return render_hybrid(spec) if fmt == "hybrid" else spec.render()


def parse_spec(text: str) -> OmniClipSpec | None:
    """Parse spec JSON as an `OmniClipSpec`, or None for non-spec text."""
    try:
        return OmniClipSpec.model_validate_json(text)
    except ValidationError:
        return None


def render_spec_json(spec_json: str, fmt: PromptFormat) -> str:
    """Render stored spec JSON in `fmt`; non-spec (legacy plain) text is returned as-is."""
    spec = parse_spec(spec_json)
    return render_prompt(spec, fmt) if spec is not None else spec_json
