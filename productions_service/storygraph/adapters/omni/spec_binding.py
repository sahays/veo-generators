"""Re-bind a compiled `OmniClipSpec` to the images a request actually sends.

The compiler binds `ref_image` / `continuity.first_frame` to the adapter's primary image plan.
Fallback rungs send fewer images, so each rung parses the spec, remaps surviving
`IMAGE_REF_k` tokens to the rung's own numbering, clears bindings for dropped images, drops the
now-false constraint tokens, applies the safety sanitizer to free-text leaves, and re-renders.
Prompts that are not an `OmniClipSpec` (legacy plain text) are only sanitized.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from ...omni.spec import ContinuitySpec, OmniClipSpec

Sanitizer = Callable[[str], str]
_REF_CONSTRAINT = "refs_are_identity_only"
_FF_CONSTRAINT = "first_frame_is_opening_frame"


def parse_spec(prompt: str) -> OmniClipSpec | None:
    """Parse a compiled prompt as an `OmniClipSpec`, or None for non-spec text."""
    try:
        return OmniClipSpec.model_validate_json(prompt)
    except ValidationError:
        return None


def _rebind_list(items: list[Any] | None, remap: dict[str, str]) -> list[Any] | None:
    if items is None:
        return None
    return [
        i.model_copy(update={"ref_image": remap.get(i.ref_image or "")}) for i in items
    ]


def _continuity(spec: OmniClipSpec, first_frame: bool) -> ContinuitySpec | None:
    cont = spec.continuity
    if cont is None:
        return None
    patched = cont.model_copy(
        update={"first_frame": cont.first_frame if first_frame else None}
    )
    return patched if (patched.first_frame or patched.opening_state) else None


def rebind_spec(
    spec: OmniClipSpec, remap: dict[str, str], first_frame: bool
) -> OmniClipSpec:
    """Return `spec` bound only to sent images (`remap`: compiled token -> sent token)."""
    sent_refs = bool(remap)
    constraints = [
        c
        for c in spec.constraints
        if (c != _REF_CONSTRAINT or sent_refs) and (c != _FF_CONSTRAINT or first_frame)
    ]
    return spec.model_copy(
        update={
            "subjects": _rebind_list(spec.subjects, remap),
            "objects": _rebind_list(spec.objects, remap),
            "setting": spec.setting.model_copy(
                update={"ref_image": remap.get(spec.setting.ref_image or "")}
            ),
            "continuity": _continuity(spec, first_frame),
            "constraints": constraints,
        }
    )


def _sanitize_tree(node: Any, sanitize: Sanitizer) -> Any:
    if isinstance(node, str):
        return sanitize(node)
    if isinstance(node, list):
        return [_sanitize_tree(n, sanitize) for n in node]
    if isinstance(node, dict):
        return {k: _sanitize_tree(v, sanitize) for k, v in node.items()}
    return node


def bind_prompt(
    prompt: str, remap: dict[str, str], first_frame: bool, sanitize: Sanitizer
) -> str:
    """Rebind + sanitize a spec prompt and re-render it; plain text is only sanitized."""
    spec = parse_spec(prompt)
    if spec is None:
        return sanitize(prompt)
    bound = rebind_spec(spec, remap, first_frame)
    cleaned = _sanitize_tree(bound.model_dump(exclude_none=True), sanitize)
    return OmniClipSpec.model_validate(cleaned).render()
