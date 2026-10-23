"""Pure shaping rules for the lean production snapshot (what the page renders initially).

- one generation run per shot: the highest `generation_run_rank` (ties -> later row wins);
- run summaries drop the heavy detail fields (served lazily by `GET .../shots/{id}/runs`);
- only assets referenced by returned runs/appearances are returned (and therefore signed).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from storygraph.schema import Appearance, Asset, GenerationRun, Scene
from storygraph.views import generation_run_rank

# Lazy-loaded via the run-history endpoint; ~85% of a run document's bytes.
RUN_DETAIL_FIELDS: frozenset[str] = frozenset(
    {
        "spec_json", "compiled_prompt", "negative_prompt",
        "shot_content_hash", "render_fallback", "clip_trim",
    }
)  # fmt: skip
# Scene inspector-only data (largest scene field); the list views need only the count.
SCENE_DETAIL_FIELDS: frozenset[str] = frozenset({"interaction_steps"})
# Pipeline-internal shot wiring no UI view reads (grep-verified against frontend/src).
SHOT_DETAIL_FIELDS: frozenset[str] = frozenset(
    {"sfx", "ref_ids", "prop_appearance_ids"}
)
# QA lists kept in summaries (small, drive card badges); other lists/dicts are detail-only.
QA_SUMMARY_LISTS: frozenset[str] = frozenset({"artifact_flags"})
COMPOSITE_KIND = "composite_sheet"
ASSET_SUMMARY_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "node_type",
        "kind",
        "version",
        "status",
        "uri",
        "qa_notes",
        "depicts_entity_ids",
    }
)


def select_active_runs(runs: Iterable[GenerationRun]) -> dict[str, GenerationRun]:
    """Best run per shot by `generation_run_rank`; on equal rank the later run wins."""
    best: dict[str, GenerationRun] = {}
    for run in runs:
        prev = best.get(run.shot_id)
        if prev is None or generation_run_rank(run) >= generation_run_rank(prev):
            best[run.shot_id] = run
    return best


def count_runs_by_shot(runs: Iterable[GenerationRun]) -> dict[str, int]:
    return dict(Counter(r.shot_id for r in runs))


def count_assets_by_kind(assets: Iterable[Asset]) -> dict[str, int]:
    return dict(Counter(a.kind for a in assets))


def _slim_qa(qa: dict[str, Any] | None) -> dict[str, Any] | None:
    if qa is None:
        return None
    return {
        k: v
        for k, v in qa.items()
        if not isinstance(v, (list, dict)) or k in QA_SUMMARY_LISTS
    }


def run_summary(run: GenerationRun, signed: dict[str, str]) -> dict[str, Any]:
    """Run dict without detail fields, with scalar-only QA and its signed video URL."""
    out = run.model_dump(mode="json", exclude=set(RUN_DETAIL_FIELDS))
    out["qa_scores"] = _slim_qa(out.get("qa_scores"))
    out["output_video_signed_url"] = signed.get(run.output_video_uri or "")
    return out


def run_detail(run: GenerationRun, signed: dict[str, str]) -> dict[str, Any]:
    """Full run dict (every attempt field) with its signed video URL."""
    out = run.model_dump(mode="json")
    out["output_video_signed_url"] = signed.get(run.output_video_uri or "")
    return out


def run_asset_ids(runs: Iterable[GenerationRun]) -> set[str]:
    """Start-frame, reference and extracted last-frame asset ids used by `runs`."""
    ids: set[str] = set()
    for r in runs:
        ids.update(r.reference_asset_ids)
        ids.update(
            a for a in (r.first_frame_asset_id, r.extracted_last_frame_asset_id) if a
        )
    return ids


def appearance_asset_ids(
    appearances: Iterable[Appearance], assets_by_id: dict[str, Asset]
) -> set[str]:
    """Non-composite asset ids embedded under each appearance card."""
    return {
        aid
        for app in appearances
        for aid in app.asset_ids
        if aid in assets_by_id and assets_by_id[aid].kind != COMPOSITE_KIND
    }


def asset_dict(asset: Asset, signed: dict[str, str]) -> dict[str, Any]:
    """Asset card projection (frontend `StoryGraphAsset`): no prompt/hash/lineage fields."""
    out = asset.model_dump(mode="json", include=set(ASSET_SUMMARY_FIELDS))
    out["signed_url"] = signed.get(asset.uri) if asset.uri else None
    return out


def scene_summary(scene: Scene) -> dict[str, Any]:
    """Scene without its interaction steps (lazy: `GET .../graph/scenes/{id}`), plus their count."""
    out = scene.model_dump(mode="json", exclude=set(SCENE_DETAIL_FIELDS))
    out["interaction_step_count"] = len(scene.interaction_steps)
    return out
