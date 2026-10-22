"""Production-identical base `RenderPackage`s for the experiment (variant A = current hybrid).

The base package of a shot is rebuilt from its latest GenerationRun: the compiled hybrid
prompt, its spec JSON and the same labelled reference sheets, so variant A is exactly what
the pipeline sends today and variants B/C only swap the media bindings + prompt.
"""

from __future__ import annotations

from ...adapters.omni.package import RenderPackage
from ...repo import Repo
from ...schema import GenerationRun, Shot
from ..prompt_ab.cases import build_labels, speaking_ids

_PREFERRED = ("approved", "rendered")


def latest_run(repo: Repo, shot_id: str) -> GenerationRun:
    runs = repo.list_generation_runs(shot_id=shot_id)
    if not runs:
        raise ValueError(f"no generation run for {shot_id}")
    good = [r for r in runs if str(r.status) in _PREFERRED] or runs
    return max(good, key=lambda r: r.attempt)


def base_package(repo: Repo, shot: Shot, run: GenerationRun) -> RenderPackage:
    """RenderPackage mirroring the pipeline's request for `shot` (first frame unset)."""
    meta = repo.get_project_meta()
    assets = {a.id: a.model_dump() for a in repo.list_assets()}
    entities = {e.id: e.model_dump() for e in repo.list_entities()}
    shot_dict = shot.model_dump()
    ref_ids = [a for a in run.reference_asset_ids if a in assets]
    labels = build_labels(ref_ids, assets, entities, speaking_ids(shot_dict))
    return RenderPackage(
        shot_id=shot.id,
        compiled_prompt=run.compiled_prompt,
        negative_prompt=run.negative_prompt,
        reference_asset_ids=ref_ids,
        reference_uris=[lbl.uri for lbl in labels],
        first_frame_asset_id=None,
        first_frame_uri=None,
        duration_s=shot.duration_s,
        aspect_ratio=meta.orientation if meta else "16:9",
        seed=run.seed,
        package_hash=run.package_hash,
        resolution="360p",
        spec_json=run.spec_json or "",
        prompt_format=run.prompt_format or "json",
        reference_labels=labels,
        project_id=meta.id if meta else "",
        visual_style_preset=meta.visual_style_preset if meta else "",
        language=meta.language if meta else "",
    )
