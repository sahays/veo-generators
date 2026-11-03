"""E2_keyframe_restyle: restyle previz frames at 1 fps, then animate with the anchored strategy.

Each second's previz frame is the composition (positions, poses, camera are correct by
construction); the image model repaints it with one labelled reference board, plus the first
restyled frame as an appearance anchor (constant depth: never an edit of an edit). Seconds
whose plan delta is empty reuse the previous restyle. The restyled frames then drive the
existing D1 `keyframe_anchored` Omni request.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, replace

from ...adapters.omni.package import RenderPackage
from ...keyframes.animate.strategies import anchored_package
from ...keyframes.plan.models import KeyframePlan, PlanInput
from ...keyframes.plate.refboard import compose_board
from ...keyframes.render.retry import with_retry
from ...schemas.previz import PrevizVariantRecord
from .context import PrevizInput, VariantDeps, frames_at
from .mapping import colour_map
from .prompts import e2_frame_prompt

ANCHOR_LINE = (
    "Image 3 is the first finished frame: match its appearance and materials exactly."
)


def _board(deps: VariantDeps, pz: PrevizInput) -> tuple[bytes, list[str]]:
    refs = [(c.name, c.ref_uri) for c in pz.inp.cast if c.ref_uri]
    refs += [(o.name, o.ref_uri) for o in pz.inp.objects if o.ref_uri]
    if pz.inp.location_ref_uri:
        refs.append((pz.inp.location_name, pz.inp.location_ref_uri))
    return compose_board([(name, deps.repo.blobs.get_bytes(uri)) for name, uri in refs])


def _seconds(pz: PrevizInput) -> list[float]:
    last = pz.inp.duration_s - 0.05
    return [min(float(k.t), last) for k in pz.plan.keyframes]


def restyle_frames(deps: VariantDeps, pz: PrevizInput) -> list[bytes]:
    """Every second is restyled: previz motion is not tied to the 2D plan's deltas."""
    board, labels = _board(deps, pz)
    mapped = colour_map(pz.scene)
    location = pz.inp.location_name if pz.inp.location_name in labels else ""
    aspect = "16:9" if pz.scene.render.width >= pz.scene.render.height else "9:16"
    out: list[bytes] = []
    for frame, png in zip(
        pz.plan.keyframes, frames_at(pz.video, _seconds(pz)), strict=True
    ):
        prompt = e2_frame_prompt(frame.t, mapped, labels, deps.style, location)
        images = [png, *([board] if board else []), *(out[:1])]
        text = prompt + ("\n" + ANCHOR_LINE if out else "")
        out.append(
            with_retry(
                lambda: deps.image_gen.generate(text, images, aspect, 7),
                "previz.e2.frame",
            )
        )
    return out


def store_frames(
    deps: VariantDeps, shot_id: str, tag: str, frames: list[bytes]
) -> list[str]:
    uris: list[str] = []
    for t, png in enumerate(frames):
        sha = hashlib.sha256(png).hexdigest()[:8]
        uris.append(
            deps.put(f"previz/{shot_id}/{tag}_t{t:02d}_{sha}.png", png, "image/png")
        )
    return uris


@dataclass(frozen=True)
class Animated:
    video_uri: str
    prompt: str
    model: str


def animate_keyframes(
    deps: VariantDeps,
    inp: PlanInput,
    plan: KeyframePlan,
    base: RenderPackage,
    uris: list[str],
    tag: str,
) -> Animated:
    """D1 `keyframe_anchored` Omni render of 1 fps keyframes (`uris` indexed by second)."""
    caps = deps.video_gen.caps
    pkg = anchored_package(base, inp, plan, uris, caps.max_reference_images, True)
    pkg = replace(pkg, shot_id=plan.shot_id)
    video = with_retry(lambda: deps.video_gen.generate(pkg), f"previz.{tag}.generate")
    sha = hashlib.sha256(video).hexdigest()[:8]
    uri = deps.put(f"previz/{plan.shot_id}/{tag}_{sha}.mp4", video, "video/mp4")
    return Animated(uri, pkg.compiled_prompt, caps.model)


def run_e2(
    deps: VariantDeps, pz: PrevizInput, base: RenderPackage
) -> PrevizVariantRecord:
    started = time.monotonic()
    uris = store_frames(deps, pz.shot.id, "e2", restyle_frames(deps, pz))
    out = animate_keyframes(deps, pz.inp, pz.plan, base, uris, "e2")
    return PrevizVariantRecord(
        variant="E2_keyframe_restyle",
        status="done",
        video_uri=out.video_uri,
        frame_uris=uris,
        model=f"{deps.image_model} + {out.model}",
        prompt=out.prompt,
        seconds=round(time.monotonic() - started, 1),
    )
