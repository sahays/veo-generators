"""Production-identical base Omni package for a shot (references, spec, safety context).

Same composition as the S8_RENDER attempt (`select_references` -> `compile_shot` -> labelled
`RenderPackage`) without retry feedback; the variants then swap media bindings + prompt.
"""

from __future__ import annotations

from ...adapters.omni.package import RenderPackage, build_ref_labels, to_render_package
from ...budget import select_references
from ...compile import compile_shot
from ...config import Config, VideoProviderCfg
from ...pipeline.shot_attempt import resolve_target_resolution
from ...repo import Repo
from ...schema import Shot
from ...views import shot_view


def base_package(
    repo: Repo, cfg: Config, caps: VideoProviderCfg, shot: Shot
) -> RenderPackage:
    view = shot_view(repo, shot.id)
    plan = select_references(view, cfg, caps=caps, repo=repo, allow_composites=True)
    pkg = compile_shot(
        view,
        plan,
        cfg,
        caps=caps,
        project_id=repo.project_id,
        resolution=resolve_target_resolution(repo),
    )
    meta = repo.get_project_meta()
    return to_render_package(
        pkg,
        build_ref_labels(view, plan.selected_assets),
        project_id=repo.project_id,
        visual_style_preset=view.style_guide.visual_style_preset
        or (meta.visual_style_preset if meta else ""),
        language=meta.language if meta else "",
    )
