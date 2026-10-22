"""Build Gemini Omni `interactions.create` input blocks with labelled, prioritised images.

Decision (first frame): the Interactions schema (`google-genai` 2.29 `ImageContent`) has no
per-image role field, but the Omni docs ("Using tags in prompts to set image and video roles")
bind media roles with a prompt header: `[# Sources <FIRST_FRAME>@Image1]
[# References <IMAGE_REF_0>@Image2 ...]`. In `first_frame_mode="tag"` the previous shot's last
frame is sent as Image1 and bound as the starting frame (never as an identity reference). In
`"drop"` mode it is omitted and continuity relies on the prompt text.

Keyframe strategies (storygraph/keyframes) add two bindings from the same docs section:
`<LAST_FRAME>@Image2` (only together with a bound first frame: first/last interpolation) and
`<VIDEO_0>@Video1` (a source video to edit, e.g. the 1 fps animatic). A source video is the
primary content, so it replaces frame bindings; identity refs stay `IMAGE_REF_k`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ...compile import Package
from ...omni.spec import PromptFormat
from .package import RefLabel, RenderPackage
from .spec_binding import Sanitizer, bind_prompt

FirstFrameMode = Literal["tag", "drop"]

_ROLE_RANK: dict[str, int] = {
    "keyframe": 0,
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
    last_frame_bound: bool = False
    video_uri: str | None = None


@dataclass(frozen=True)
class ImageSlots:
    """Adapter image plan: bound first-frame URI (Image1) and refs in `IMAGE_REF_k` order."""

    first_frame_uri: str | None
    refs: tuple[RefLabel, ...]
    last_frame_uri: str | None = None
    video_uri: str | None = None

    @property
    def frame_uris(self) -> tuple[str, ...]:
        """Bound frame images in send order (Image1 = first, Image2 = last)."""
        return tuple(u for u in (self.first_frame_uri, self.last_frame_uri) if u)

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
    if label.role == "keyframe":
        return (
            f"Reference image {image_no} {tag} — STATE REFERENCE at t={label.t_s:g}s of this "
            "same continuous shot (who is where, outfits, props at that second). Not a shot "
            "to insert; never show it as a frame or cut to it:"
        )
    if label.role == "composite" and len(label.names) >= 2:
        who = f"{label.names[0]} (left) and {label.names[1]} (right) identity sheet"
    elif label.names:
        who = f"{' and '.join(label.names)} identity"
    else:
        who = "subject identity"
    return f"Reference image {image_no} {tag} — {who} (appearance only, not a frame):"


def _sources(slots: ImageSlots) -> list[str]:
    tags = ["<FIRST_FRAME>@Image1"] if slots.first_frame_uri else []
    tags += ["<LAST_FRAME>@Image2"] if slots.last_frame_uri else []
    tags += ["<VIDEO_0>@Video1"] if slots.video_uri else []
    return tags


def _role_header(slots: ImageSlots) -> str:
    offset = len(slots.frame_uris) + 1
    sources = _sources(slots)
    parts: list[str] = [f"[# Sources {' '.join(sources)}]"] if sources else []
    if slots.refs:
        refs = " ".join(
            f"<IMAGE_REF_{i}>@Image{i + offset}" for i in range(len(slots.refs))
        )
        parts.append(f"[# References {refs}]")
    return " ".join(parts)


def _select_task(slots: ImageSlots) -> str | None:
    if slots.video_uri or slots.last_frame_uri:
        return None  # source edit / interpolation: the tag header drives the mode
    first_frame, ref_count = bool(slots.first_frame_uri), len(slots.refs)
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
    last_frame_uri: str | None = None,
    video_uri: str | None = None,
) -> ImageSlots:
    """Decide which images are sent and their order (shared by compiler and request builder).

    The location sheet is always kept when at least two reference slots remain. A last
    frame is bound only together with a first frame; a source video replaces both.
    """
    video = video_uri if _is_gcs(video_uri) else None
    use_ff = (
        not video
        and first_frame_mode == "tag"
        and _is_gcs(first_frame_uri)
        and max_images >= 1
    )
    use_lf = use_ff and _is_gcs(last_frame_uri) and max_images >= 2
    budget = max(0, max_images - int(use_ff) - int(use_lf))
    frames = {first_frame_uri, last_frame_uri}
    candidates = [lbl for lbl in labels if _is_gcs(lbl.uri) and lbl.uri not in frames]
    refs = _fit_refs(order_labels(candidates), budget)
    return ImageSlots(
        first_frame_uri if use_ff else None,
        refs,
        last_frame_uri if use_lf else None,
        video,
    )


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
    keep_video: bool = True,
) -> OmniRequest:
    """Role-tag header + spec bound to the sent images + interleaved (label, image) blocks.

    `prompt` is the spec JSON (`Package.spec_source`) or legacy plain text; `bound_tokens`
    is the asset_id -> `IMAGE_REF_k` map the compiler used (None = this request's own plan).
    The rebound spec is re-rendered in `package.prompt_format` (legacy packages without
    `spec_json` keep JSON), so the text always names exactly the images this rung sends.
    """
    slots = plan_image_slots(
        package_labels(package),
        package.first_frame_uri,
        max_images,
        first_frame_mode,
        package.last_frame_uri,
        package.source_video_uri if keep_video else None,
    )
    fmt: PromptFormat = package.prompt_format if package.spec_json else "json"
    remap = _remap(slots, bound_tokens)
    body = bind_prompt(prompt, remap, bool(slots.first_frame_uri), sanitize, fmt)
    header = _role_header(slots)
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": "\n".join(p for p in (header, body) if p)}
    ]
    blocks += _source_blocks(slots)
    uris: list[str] = list(slots.frame_uris)
    for idx, label in enumerate(slots.refs):
        caption = reference_label_text(len(uris) + 1, idx, label)
        blocks += [{"type": "text", "text": caption}, _image_block(label.uri)]
        uris.append(label.uri)
    return OmniRequest(
        blocks,
        _select_task(slots),
        tuple(uris),
        bool(slots.first_frame_uri),
        bool(slots.last_frame_uri),
        slots.video_uri,
    )


def _source_blocks(slots: ImageSlots) -> list[dict[str, Any]]:
    """Captioned frame images (Image1/Image2) and the source video, in tag order."""
    out: list[dict[str, Any]] = []
    if slots.first_frame_uri:
        caption = (
            "Image1 — starting frame (first keyframe)."
            if slots.last_frame_uri
            else "Image1 — starting frame: the last frame of the previous shot."
        )
        out += [{"type": "text", "text": caption}, _image_block(slots.first_frame_uri)]
    if slots.last_frame_uri:
        caption = "Image2 — final frame to transition to (last keyframe)."
        out += [{"type": "text", "text": caption}, _image_block(slots.last_frame_uri)]
    if slots.video_uri:
        caption = "Video1 — source video to edit."
        out += [{"type": "text", "text": caption}, _video_block(slots.video_uri)]
    return out


def _image_block(uri: str) -> dict[str, Any]:
    return {"type": "image", "uri": uri, "mime_type": "image/png"}


def _video_block(uri: str) -> dict[str, Any]:
    return {"type": "video", "uri": uri, "mime_type": "video/mp4"}
