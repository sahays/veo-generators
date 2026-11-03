"""E1_omni_restyle: the previz MP4 goes to Omni as `<VIDEO_0>` with the identity references.

Omni keeps the previz motion, camera and layout and only replaces appearance (colour mapping
mannequin -> character). Dialogue stays in the prompt; lip-sync on uploaded-video edits is
untested, so the spike measures it.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import replace

from ...adapters.omni.package import RenderPackage
from ...keyframes.render.retry import with_retry
from ...omni.render import parse_spec
from ...schemas.previz import PrevizVariantRecord
from .context import PrevizInput, VariantDeps
from .mapping import colour_map
from .prompts import e1_prompt


def e1_package(base: RenderPackage, pz: PrevizInput, style: str) -> RenderPackage:
    prompt = e1_prompt(parse_spec(base.spec_source), colour_map(pz.scene), style)
    return replace(
        base,
        compiled_prompt=prompt,
        spec_json="",
        first_frame_asset_id=None,
        first_frame_uri=None,
        last_frame_uri=None,
        source_video_uri=pz.video_uri,
        duration_s=pz.inp.duration_s,
    )


def run_e1(
    deps: VariantDeps, pz: PrevizInput, base: RenderPackage
) -> PrevizVariantRecord:
    pkg = e1_package(base, pz, deps.style)
    started = time.monotonic()
    video = with_retry(lambda: deps.video_gen.generate(pkg), "previz.e1.generate")
    sha = hashlib.sha256(video).hexdigest()[:8]
    uri = deps.put(f"previz/{pz.shot.id}/e1_{sha}.mp4", video, "video/mp4")
    return PrevizVariantRecord(
        variant="E1_omni_restyle",
        status="done",
        video_uri=uri,
        model=deps.video_gen.caps.model,
        prompt=pkg.compiled_prompt,
        seconds=round(time.monotonic() - started, 1),
    )
