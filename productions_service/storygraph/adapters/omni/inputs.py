"""Build Gemini Omni `interactions.create` input blocks with labelled, prioritised images.

Decision (first frame): the Interactions schema (`google-genai` 2.29 `ImageContent`) has no
per-image role field, but the Omni docs ("Using tags in prompts to set image and video roles")
bind media roles with a prompt header: `[# Sources <FIRST_FRAME>@Image1]
[# References <IMAGE_REF_0>@Image2 ...]`. In `first_frame_mode="tag"` the previous shot's last
frame is sent as Image1 and bound as the starting frame (never as an identity reference). In
`"drop"` mode it is omitted and continuity relies on the prompt text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ...compile import Package
from .package import RefLabel, RenderPackage
from .spec_binding import Sanitizer, bind_prompt

FirstFrameMode = Literal["tag", "drop"]

_ROLE_RANK: dict[str, int] = {
    "character": 0,
    "composite": 1,
    "location": 2,
    "prop": 3,
    "other": 4,
}


@dataclass(frozen=True)
class OmniRequest:
    """Fully assembled Omni input plus the audit facts needed for fallback logging."""

    blocks: list[dict[str, Any]]
    task: str | None
    image_uris: tuple[str, ...]
    first_frame_bound: bool


@dataclass(frozen=True)
class ImageSlots:
    """Adapter image plan: bound first-frame URI (Image1) and refs in `IMAGE_REF_k` order."""

    first_frame_uri: str | None
    refs: tuple[RefLabel, ...]

    def ref_tokens(self) -> dict[str, str]:
        """asset_id -> `IMAGE_REF_k` role tag, exactly as the request header binds them."""
        return {lbl.asset_id: f"IMAGE_REF_{k}" for k, lbl in enumerate(self.refs)}


def _is_gcs(uri: str | None) -> bool:
    return bool(uri) and str(uri).startswith("gs://")


def package_labels(package: Package) -> list[RefLabel]:
    """Return labels for every gs:// reference, synthesising generic ones for plain packages."""
    if isinstance(package, RenderPackage) and package.reference_labels:
        return [lbl for lbl in package.reference_labels if _is_gcs(lbl.uri)]
    return [
        RefLabel(uri=u, asset_id=u, names=(), role="other")
        for u in dict.fromkeys(package.reference_uris)
        if _is_gcs(u)
    ]


def order_labels(labels: list[RefLabel]) -> list[RefLabel]:
    """Speaking characters, then other characters, composites, location, props (stable)."""
    indexed = list(enumerate(labels))
    indexed.sort(key=lambda p: (_ROLE_RANK[p[1].role], not p[1].speaking, p[0]))
    return [lbl for _, lbl in indexed]


def reference_label_text(image_no: int, ref_idx: int, label: RefLabel) -> str:
    """Short inline caption placed immediately before a reference image block."""
    tag = f"<IMAGE_REF_{ref_idx}>"
    if label.role == "composite" and len(label.names) >= 2:
        who = f"{label.names[0]} (left) and {label.names[1]} (right) identity sheet"
    elif label.names:
        who = f"{' and '.join(label.names)} identity"
    else:
        who = "subject identity"
    return f"Reference image {image_no} {tag} — {who} (appearance only, not a frame):"


def _role_header(first_frame: bool, ref_count: int) -> str:
    offset = 2 if first_frame else 1
    parts: list[str] = ["[# Sources <FIRST_FRAME>@Image1]"] if first_frame else []
    if ref_count:
        refs = " ".join(f"<IMAGE_REF_{i}>@Image{i + offset}" for i in range(ref_count))
        parts.append(f"[# References {refs}]")
    return " ".join(parts)


def _select_task(first_frame: bool, ref_count: int) -> str | None:
    if first_frame and ref_count:
        return (
            None  # mixed roles: the tag header drives the mode (docs recommend no task)
        )
    if first_frame:
        return "image_to_video"
    return "reference_to_video" if ref_count else "text_to_video"


def _fit_refs(ordered: list[RefLabel], budget: int) -> tuple[RefLabel, ...]:
    """Truncate to `budget` while keeping the location/setting sheet (needs >= 2 slots)."""
    if len(ordered) <= budget:
        return tuple(ordered)
    loc = next((lbl for lbl in ordered if lbl.role == "location"), None)
    if loc is None or budget < 2:
        return tuple(ordered[:budget])
    others = [lbl for lbl in ordered if lbl is not loc][: budget - 1]
    return tuple(order_labels([*others, loc]))


def plan_image_slots(
    labels: list[RefLabel],
    first_frame_uri: str | None,
    max_images: int,
    first_frame_mode: FirstFrameMode = "tag",
) -> ImageSlots:
    """Decide which images are sent and their order (shared by compiler and request builder).

    The location sheet is always kept when at least two reference slots remain.
    """
    use_ff = first_frame_mode == "tag" and _is_gcs(first_frame_uri) and max_images >= 1
    budget = max(0, max_images - (1 if use_ff else 0))
    candidates = [
        lbl for lbl in labels if _is_gcs(lbl.uri) and lbl.uri != first_frame_uri
    ]
    refs = _fit_refs(order_labels(candidates), budget)
    return ImageSlots(first_frame_uri if use_ff else None, refs)


def _remap(slots: ImageSlots, bound_tokens: dict[str, str] | None) -> dict[str, str]:
    """Compiled `IMAGE_REF_k` token -> token this request binds (dropped refs absent)."""
    sent = slots.ref_tokens()
    compiled = sent if bound_tokens is None else bound_tokens
    return {tok: sent[aid] for aid, tok in compiled.items() if aid in sent}


def build_omni_request(
    package: Package,
    prompt: str,
    max_images: int,
    first_frame_mode: FirstFrameMode = "tag",
    bound_tokens: dict[str, str] | None = None,
    sanitize: Sanitizer = str.strip,
) -> OmniRequest:
    """Role-tag header + spec bound to the sent images + interleaved (label, image) blocks.

    `prompt` is the compiled spec (or legacy text); `bound_tokens` is the asset_id ->
    `IMAGE_REF_k` map the compiler used (None = this request's own plan).
    """
    slots = plan_image_slots(
        package_labels(package), package.first_frame_uri, max_images, first_frame_mode
    )
    ff_uri, refs = slots.first_frame_uri, slots.refs
    body = bind_prompt(prompt, _remap(slots, bound_tokens), bool(ff_uri), sanitize)
    header = _role_header(bool(ff_uri), len(refs))
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": "\n".join(p for p in (header, body) if p)}
    ]
    uris: list[str] = []
    if ff_uri:
        caption = "Image1 — starting frame: the last frame of the previous shot."
        blocks += [{"type": "text", "text": caption}, _image_block(ff_uri)]
        uris.append(ff_uri)
    for idx, label in enumerate(refs):
        caption = reference_label_text(len(uris) + 1, idx, label)
        blocks += [{"type": "text", "text": caption}, _image_block(label.uri)]
        uris.append(label.uri)
    return OmniRequest(
        blocks, _select_task(bool(ff_uri), len(refs)), tuple(uris), bool(ff_uri)
    )


def _image_block(uri: str) -> dict[str, Any]:
    return {"type": "image", "uri": uri, "mime_type": "image/png"}
